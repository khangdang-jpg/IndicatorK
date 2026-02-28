/**
 * Cloudflare Workers Command Gateway for IndicatorK Bot
 * Handles Telegram webhook commands while keeping batch processing on GitHub Actions
 */

export default {
  async fetch(request, env) {
    if (request.method === 'GET') {
      return new Response('IndicatorK Bot Command Gateway v1.0', { status: 200 });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    try {
      const update = await request.json();
      await handleTelegramUpdate(update, env);
      return new Response(JSON.stringify({ ok: true }), {
        headers: { 'Content-Type': 'application/json' }
      });
    } catch (error) {
      console.error('Error handling update:', error);
      return new Response('Internal error', { status: 500 });
    }
  }
};

async function handleTelegramUpdate(update, env) {
  const message = update.message;
  if (!message || !message.text?.startsWith('/')) {
    return; // Ignore non-command messages
  }

  const chatId = message.chat.id.toString();
  const adminChatId = env.TELEGRAM_ADMIN_CHAT_ID;

  // Security: Only admin can use commands
  if (chatId !== adminChatId) {
    await sendTelegramMessage(chatId, 'Access denied', env);
    return;
  }

  console.log(`Processing command: ${message.text} from ${chatId}`);

  const response = await handleCommand(message.text, env);
  await sendTelegramMessage(chatId, response, env);
}

const COMMAND_HANDLERS = {
  '/buy': (args, env) => handleTrade(args, 'BUY', env),
  '/sell': (args, env) => handleTrade(args, 'SELL', env),
  '/setcash': (args, env) => handleSetCash(args, env),
  '/status': (args, env) => handleStatus(env),
  '/plan': (args, env) => handlePlan(env),
  '/help': (args, env) => handleHelp()
};

async function handleCommand(text, env) {
  const parts = text.trim().split(/\s+/);
  const command = parts[0].toLowerCase();
  const args = parts.slice(1).join(' ');

  const handler = COMMAND_HANDLERS[command];
  if (!handler) {
    return `Unknown command: ${command}\\nType /help for available commands.`;
  }

  try {
    return await handler(args, env);
  } catch (error) {
    console.error(`Command error for '${text}':`, error);
    return `Error: ${error.message}`;
  }
}

// Command implementations
async function handleTrade(args, side, env) {
  if (!args) {
    return `Usage: /${side.toLowerCase()} SYMBOL QTY PRICE [fee=N] [note=TEXT]`;
  }

  const parsed = parseTradeArgs(args);
  if (!parsed.valid) {
    return parsed.error;
  }

  const trade = {
    timestamp_iso: new Date().toISOString(),
    asset_class: 'stock',
    symbol: parsed.symbol.toUpperCase(),
    side: side,
    qty: parsed.qty,
    price: parsed.price,
    fee: parsed.fee || 0,
    note: parsed.note || ''
  };

  await appendTrade(trade, env);

  const total = parsed.price * parsed.qty + (trade.fee * (side === 'BUY' ? 1 : -1));
  return `Recorded ${side} ${trade.symbol}\\n` +
         `Qty: ${trade.qty.toLocaleString()} @ ${trade.price.toLocaleString()}\\n` +
         `Asset: ${trade.asset_class} | Fee: ${trade.fee.toLocaleString()}\\n` +
         `Total: ${total.toLocaleString()}`;
}

async function handleSetCash(args, env) {
  if (!args) {
    return 'Usage: /setcash AMOUNT';
  }

  const amount = parseFloat(args.trim());
  if (isNaN(amount) || amount < 0) {
    return 'Error: Invalid cash amount';
  }

  const trade = {
    timestamp_iso: new Date().toISOString(),
    asset_class: 'fund',
    symbol: 'CASH',
    side: 'CASH',
    qty: 1,
    price: amount,
    fee: 0,
    note: 'setcash'
  };

  await appendTrade(trade, env);
  return `Cash balance set to ${amount.toLocaleString()}`;
}

async function handleStatus(env) {
  const trades = await getTrades(env);
  const portfolioState = computePortfolioState(trades);
  return formatStatusMessage(portfolioState);
}

async function handlePlan(env) {
  try {
    const plan = await getWeeklyPlan(env);
    const trades = await getTrades(env);
    const portfolioState = computePortfolioState(trades);
    return formatPlanSummary(plan, portfolioState.totalValue);
  } catch (error) {
    console.error('Error loading plan:', error);
    return "No weekly plan generated yet. Run the weekly workflow first.";
  }
}

function handleHelp() {
  return `🤖 IndicatorK Trading Bot 📈

💰 TRADING COMMANDS
• /buy SYMBOL QTY PRICE - Record buy trade
• /sell SYMBOL QTY PRICE - Record sell trade
• /setcash AMOUNT - Set cash balance

📊 PORTFOLIO COMMANDS
• /status - View portfolio & positions
• /plan - View weekly trading plan
• /help - Show this message

⚡ Instant responses via Cloudflare Workers`;
}

// Utility functions
function parseTradeArgs(args) {
  const tokens = args.split(/\s+/);
  if (tokens.length < 3) {
    return { valid: false, error: 'Usage: SYMBOL QTY PRICE [fee=N] [note=TEXT]' };
  }

  const symbol = tokens[0].toUpperCase();
  const qty = parseFloat(tokens[1]);
  const price = parseFloat(tokens[2]);

  if (!symbol || isNaN(qty) || isNaN(price) || qty <= 0 || price <= 0) {
    return { valid: false, error: 'Invalid symbol, quantity, or price' };
  }

  let fee = 0;
  let note = '';

  // Parse optional parameters
  for (let i = 3; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.includes('=')) {
      const [key, val] = token.split('=', 2);
      if (key.toLowerCase() === 'fee') {
        fee = parseFloat(val) || 0;
      } else if (key.toLowerCase() === 'note') {
        note = val;
      }
    } else {
      note = (note + ' ' + token).trim();
    }
  }

  return { valid: true, symbol, qty, price, fee, note };
}

// GitHub API integration
async function getTrades(env) {
  try {
    const url = `https://raw.githubusercontent.com/${env.GITHUB_REPO}/main/data/trades.csv`;
    const response = await fetch(url);
    const csvText = await response.text();
    return parseTradesCsv(csvText);
  } catch (error) {
    console.error('Error fetching trades:', error);
    return [];
  }
}

async function getWeeklyPlan(env) {
  if (!env.GITHUB_REPO) {
    throw new Error('GITHUB_REPO environment variable not set');
  }
  const url = `https://raw.githubusercontent.com/${env.GITHUB_REPO}/main/data/weekly_plan.json`;
  console.log('Fetching weekly plan from:', url);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load weekly plan: ${response.status} from ${url}`);
  }
  return await response.json();
}

async function appendTrade(trade, env) {
  // Get current trades.csv content and SHA
  const { content, sha } = await getFileContent('data/trades.csv', env);

  // Parse current trades
  const trades = parseTradesCsv(content);

  // Add new trade
  trades.push(trade);

  // Convert back to CSV
  const newCsv = formatTradesCsv(trades);

  // Commit updated file
  await updateFile('data/trades.csv', newCsv, sha, `Add ${trade.side} ${trade.symbol}`, env);
}

async function getFileContent(path, env) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}`;
  const response = await fetch(url, {
    headers: { 'Authorization': `token ${env.GITHUB_TOKEN}` }
  });

  if (response.status === 404) {
    // File doesn't exist, return empty content
    return { content: '', sha: null };
  }

  const data = await response.json();
  const content = atob(data.content); // Decode base64
  return { content, sha: data.sha };
}

async function updateFile(path, content, sha, message, env) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}`;
  const body = {
    message: message,
    content: btoa(content), // Base64 encode
  };

  if (sha) {
    body.sha = sha;
  }

  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      'Authorization': `token ${env.GITHUB_TOKEN}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  });

  return await response.json();
}

// CSV parsing and formatting
function parseTradesCsv(csvText) {
  if (!csvText || csvText.trim() === '') {
    return [];
  }

  const lines = csvText.trim().split('\\n');
  const trades = [];

  // Skip header line
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    const parts = line.split(',');
    if (parts.length >= 7) {
      trades.push({
        timestamp_iso: parts[0],
        asset_class: parts[1],
        symbol: parts[2],
        side: parts[3],
        qty: parseFloat(parts[4]),
        price: parseFloat(parts[5]),
        fee: parseFloat(parts[6] || 0),
        note: parts[7] || ''
      });
    }
  }

  return trades;
}

function formatTradesCsv(trades) {
  const header = 'timestamp_iso,asset_class,symbol,side,qty,price,fee,note';
  const rows = trades.map(t =>
    `${t.timestamp_iso},${t.asset_class},${t.symbol},${t.side},${t.qty},${t.price},${t.fee},"${t.note}"`
  );
  return [header, ...rows].join('\\n');
}

// Portfolio computation (simplified version of Python logic)
function computePortfolioState(trades) {
  const positions = {};
  let cash = 0;

  for (const trade of trades) {
    if (trade.side === 'CASH') {
      cash = trade.price;
      continue;
    }

    const symbol = trade.symbol;
    if (!positions[symbol]) {
      positions[symbol] = {
        symbol: symbol,
        asset_class: trade.asset_class,
        qty: 0,
        avg_cost: 0,
        realized_pnl: 0
      };
    }

    const pos = positions[symbol];

    if (trade.side === 'BUY') {
      const total_cost = pos.avg_cost * pos.qty + trade.price * trade.qty;
      pos.qty += trade.qty;
      pos.avg_cost = pos.qty > 0 ? total_cost / pos.qty : 0;
      cash -= trade.price * trade.qty + trade.fee;
    } else if (trade.side === 'SELL') {
      if (pos.qty > 0) {
        const realized = (trade.price - pos.avg_cost) * Math.min(trade.qty, pos.qty);
        pos.realized_pnl += realized;
        pos.qty -= trade.qty;
        cash += trade.price * trade.qty - trade.fee;
      }
      if (pos.qty <= 0) {
        pos.qty = 0;
      }
    }

    pos.asset_class = trade.asset_class;
  }

  // Remove closed positions
  const activePositions = {};
  for (const [symbol, pos] of Object.entries(positions)) {
    if (pos.qty > 0) {
      activePositions[symbol] = pos;
    }
  }

  let totalValue = cash;
  for (const pos of Object.values(activePositions)) {
    totalValue += pos.avg_cost * pos.qty; // Use avg_cost as current price estimate
  }

  return {
    positions: activePositions,
    cash: cash,
    totalValue: totalValue
  };
}

// Message formatting
function formatStatusMessage(state) {
  let msg = `*Portfolio Status*\\n\\n`;
  msg += `💰 Cash: ${state.cash.toLocaleString()} ₫\\n`;
  msg += `📊 Total Value: ${state.totalValue.toLocaleString()} ₫\\n\\n`;

  const positions = Object.values(state.positions);
  if (positions.length === 0) {
    msg += `📈 Positions: None`;
  } else {
    msg += `📈 Positions (${positions.length}):\\n`;
    for (const pos of positions) {
      const marketValue = pos.avg_cost * pos.qty;
      msg += `• ${pos.symbol}: ${pos.qty.toLocaleString()} @ ${pos.avg_cost.toLocaleString()} ` +
             `(${marketValue.toLocaleString()} ₫)\\n`;
    }
  }

  return msg;
}

function formatPlanSummary(plan, totalValue) {
  let msg = `*Weekly Plan Summary*\\n\\n`;
  msg += `📅 Generated: ${new Date(plan.generated_at).toLocaleDateString()}\\n`;
  msg += `💰 Portfolio Value: ${totalValue.toLocaleString()} ₫\\n\\n`;

  if (plan.recommendations && plan.recommendations.length > 0) {
    msg += `📋 Recommendations (${plan.recommendations.length}):\\n`;
    for (const rec of plan.recommendations.slice(0, 5)) { // Show first 5
      msg += `• ${rec.action} ${rec.symbol}`;
      if (rec.buy_zone_low && rec.buy_zone_high) {
        msg += ` (${rec.buy_zone_low.toLocaleString()}-${rec.buy_zone_high.toLocaleString()})`;
      }
      msg += `\\n`;
    }
    if (plan.recommendations.length > 5) {
      msg += `... and ${plan.recommendations.length - 5} more\\n`;
    }
  } else {
    msg += `📋 No recommendations available`;
  }

  return msg;
}

// Telegram API
async function sendTelegramMessage(chatId, text, env) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      text: text,
      parse_mode: 'Markdown'
    })
  });

  if (!response.ok) {
    // Retry without parse_mode if markdown fails
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        text: text
      })
    });
  }
}