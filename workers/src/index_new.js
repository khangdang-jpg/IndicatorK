/**
 * Cloudflare Workers Command Gateway for IndicatorK Bot - Atomic State Version
 *
 * Handles Telegram webhook commands with atomic portfolio state management.
 * Features race-condition-safe operations, optimistic locking, and audit trails.
 */

import {
  handleMoneyOperation,
  validateMoneyOperation,
  formatOperationSuccess
} from './atomic_operations.js';

export default {
  async fetch(request, env) {
    if (request.method === 'GET') {
      return new Response('IndicatorK Bot Command Gateway v2.0 (Atomic State)', { status: 200 });
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

  try {
    const response = await handleCommand(message.text, env);
    await sendTelegramMessage(chatId, response, env);
  } catch (error) {
    console.error(`Command error for '${message.text}':`, error);
    const errorMessage = `❌ Error: ${error.message}`;
    await sendTelegramMessage(chatId, errorMessage, env);
  }
}

// Command routing with atomic money operations
const COMMAND_HANDLERS = {
  // Money operations (atomic)
  '/buy': (args, env) => handleMoneyCommand('buy', args, env, parseTradeArgs),
  '/sell': (args, env) => handleMoneyCommand('sell', args, env, parseTradeArgs),
  '/setcash': (args, env) => handleMoneyCommand('setcash', args, env, parseCashArgs),
  '/dividend': (args, env) => handleMoneyCommand('dividend', args, env, parseDividendArgs),
  '/fee': (args, env) => handleMoneyCommand('fee', args, env, parseFeeArgs),

  // Read-only operations
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
    return `Unknown command: ${command}\nType /help for available commands.`;
  }

  return await handler(args, env);
}

/**
 * Universal handler for money operations using atomic framework
 */
async function handleMoneyCommand(operationType, args, env, parser) {
  if (!args && operationType !== 'status') {
    return getUsageMessage(operationType);
  }

  try {
    // Parse command arguments
    const operationData = parser(args, operationType);

    // Execute atomic money operation
    const result = await handleMoneyOperation(operationType, operationData, env);

    return result.message;

  } catch (error) {
    console.error(`Money operation error (${operationType}):`, error.message);
    throw error; // Will be caught by command handler and formatted
  }
}

function getUsageMessage(operationType) {
  const messages = {
    'buy': 'Usage: /buy SYMBOL QTY PRICE [fee=N] [note=TEXT]',
    'sell': 'Usage: /sell SYMBOL QTY PRICE [fee=N] [note=TEXT]',
    'setcash': 'Usage: /setcash AMOUNT [reason=TEXT]',
    'dividend': 'Usage: /dividend SYMBOL AMOUNT',
    'fee': 'Usage: /fee AMOUNT [note=TEXT]'
  };
  return messages[operationType] || 'Invalid usage';
}

// Command argument parsers
function parseTradeArgs(args, side) {
  const tokens = args.split(/\s+/);
  if (tokens.length < 3) {
    throw new Error('Usage: SYMBOL QTY PRICE [fee=N] [note=TEXT]');
  }

  const symbol = tokens[0].toUpperCase();
  const qty = parseFloat(tokens[1]);
  const price = parseFloat(tokens[2]);

  if (!symbol || isNaN(qty) || isNaN(price) || qty <= 0 || price <= 0) {
    throw new Error('Invalid symbol, quantity, or price');
  }

  let fee = 0;
  let note = '';
  let asset_class = 'stock';

  // Parse optional parameters
  for (let i = 3; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.includes('=')) {
      const [key, val] = token.split('=', 2);
      switch(key.toLowerCase()) {
        case 'fee':
          fee = parseFloat(val) || 0;
          break;
        case 'note':
          note = val;
          break;
        case 'asset':
          asset_class = val.toLowerCase();
          break;
      }
    } else {
      note = (note + ' ' + token).trim();
    }
  }

  return { symbol, qty, price, fee, note, asset_class, side: side.toUpperCase() };
}

function parseCashArgs(args) {
  const tokens = args.split(/\s+/);
  if (tokens.length < 1) {
    throw new Error('Usage: /setcash AMOUNT [reason=TEXT]');
  }

  const amount = parseFloat(tokens[0]);
  if (isNaN(amount) || amount < 0) {
    throw new Error('Invalid cash amount. Must be positive number.');
  }

  let reason = 'manual_adjustment';

  // Look for reason= parameter
  const reasonMatch = args.match(/reason=(\w+)/);
  if (reasonMatch) {
    reason = reasonMatch[1];
  }

  return { amount, reason };
}

function parseDividendArgs(args) {
  const tokens = args.split(/\s+/);
  if (tokens.length < 2) {
    throw new Error('Usage: /dividend SYMBOL AMOUNT');
  }

  const symbol = tokens[0].toUpperCase();
  const amount = parseFloat(tokens[1]);

  if (!symbol || isNaN(amount) || amount <= 0) {
    throw new Error('Invalid symbol or dividend amount');
  }

  return { symbol, amount };
}

function parseFeeArgs(args) {
  const tokens = args.split(/\s+/);
  if (tokens.length < 1) {
    throw new Error('Usage: /fee AMOUNT [note]');
  }

  const amount = parseFloat(tokens[0]);
  if (isNaN(amount) || amount <= 0) {
    throw new Error('Invalid fee amount');
  }

  const note = tokens.slice(1).join(' ') || 'manual_fee';

  return { amount, note };
}

// Read-only command handlers
async function handleStatus(env) {
  try {
    const state = await getPortfolioState(env);
    return formatStatusMessage(state);
  } catch (error) {
    console.error('Error in handleStatus:', error);
    throw new Error('Failed to load portfolio status');
  }
}

async function handlePlan(env) {
  try {
    const plan = await getWeeklyPlan(env);
    const state = await getPortfolioState(env);

    // Use cached AI analysis from plan
    const aiAnalysis = plan.ai_analysis || null;

    return formatPlanSummary(plan, state.cash + getTotalPositionValue(state.positions), aiAnalysis);
  } catch (error) {
    console.error('Error in handlePlan:', error);
    return "No weekly plan generated yet. Run the weekly workflow first.";
  }
}

function handleHelp() {
  return `🤖 IndicatorK Trading Bot v2.0 📈

💰 TRADING COMMANDS
• /buy SYMBOL QTY PRICE [fee=N] - Record buy trade
• /sell SYMBOL QTY PRICE [fee=N] - Record sell trade
• /setcash AMOUNT [reason=TEXT] - Set cash balance

💸 INCOME & EXPENSES
• /dividend SYMBOL AMOUNT - Record dividend payment
• /fee AMOUNT [note] - Record fee or expense

📊 PORTFOLIO COMMANDS
• /status - View portfolio & positions
• /plan - View weekly trading plan
• /help - Show this message

⚡ Atomic operations with race-condition protection
🔒 Optimistic locking prevents data conflicts`;
}

// Portfolio state management (reads from atomic JSON state)
async function getPortfolioState(env) {
  try {
    const { content } = await getFileContent('data/portfolio_state.json', env);
    return JSON.parse(content);
  } catch (error) {
    console.error('Failed to load portfolio state:', error);
    throw new Error('Portfolio state not found. Run migration script first.');
  }
}

async function getWeeklyPlan(env) {
  const url = `https://raw.githubusercontent.com/${env.GITHUB_REPO}/main/data/weekly_plan.json`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load weekly plan: ${response.status}`);
  }
  return await response.json();
}

// Message formatting
function formatStatusMessage(state) {
  let msg = `*💼 Portfolio Status*\n\n`;
  msg += `💰 Cash: ${state.cash.toLocaleString()} ₫\n`;

  const positionsArray = Object.values(state.positions || {});
  const totalPositionValue = getTotalPositionValue(state.positions || {});
  const totalValue = state.cash + totalPositionValue;

  msg += `📊 Total Value: ${totalValue.toLocaleString()} ₫\n`;
  msg += `📈 Position Value: ${totalPositionValue.toLocaleString()} ₫\n\n`;

  if (positionsArray.length === 0) {
    msg += `📈 Positions: None`;
  } else {
    msg += `📈 Positions (${positionsArray.length}):\n`;
    for (const pos of positionsArray) {
      const marketValue = pos.current_price * pos.qty;
      const unrealizedPnl = pos.unrealized_pnl || 0;
      const pnlSign = unrealizedPnl >= 0 ? '+' : '';

      msg += `• ${pos.symbol}: ${pos.qty.toLocaleString()} @ ${pos.avg_cost.toLocaleString()}\n`;
      msg += `  Value: ${marketValue.toLocaleString()} ₫ (${pnlSign}${unrealizedPnl.toLocaleString()})\n`;
    }
  }

  msg += `\n📊 Total Realized P&L: ${(state.total_realized_pnl || 0).toLocaleString()} ₫`;
  msg += `\n🔢 State: seq=${state.sequence_number} | ${state.last_updated?.slice(0,16)}`;

  return msg;
}

function getTotalPositionValue(positions) {
  return Object.values(positions || {}).reduce((total, pos) => {
    return total + (pos.current_price * pos.qty);
  }, 0);
}

function formatPlanSummary(plan, totalValue, aiAnalysis = null) {
  const date = plan.generated_at ? plan.generated_at.slice(0, 10) : '?';
  const strategyId = plan.strategy_id || 'trend_momentum_atr';
  const strategyVersion = plan.strategy_version || 'v2.0.0';

  let lines = [
    `📊 ${strategyId} ${strategyVersion}`,
    `📅 ${date}  💰 ${totalValue.toLocaleString()} ₫`,
    ''
  ];

  const recommendations = plan.recommendations || [];
  if (!recommendations.length) {
    lines.push('No recommendations.');
    return lines.join('\n');
  }

  // BUY recommendations
  const buys = recommendations.filter(r => r.action === 'BUY');
  if (buys.length > 0) {
    lines.push(`🟢 BUY (${buys.length})`);
    for (const rec of buys) {
      const symbol = rec.symbol;
      const entryType = rec.entry_type || 'breakout';
      const icon = entryType === 'breakout' ? '⬆' : '⬇';
      const entryPrice = rec.entry_price || rec.buy_zone_low || 0;

      // Calculate allocation using decimal position_target_pct
      const positionPct = rec.position_target_pct || 0.1; // Default 10% as decimal
      const allocation = Math.round(positionPct * totalValue / 100000) * 100000;

      lines.push(`${symbol} ${icon} ${entryType.charAt(0).toUpperCase() + entryType.slice(1)} ${allocation.toLocaleString()} ₫`);

      // Zone and prices
      lines.push(`  Entry ${entryPrice.toLocaleString()}  Zone ${(rec.buy_zone_low || 0).toLocaleString()}–${(rec.buy_zone_high || 0).toLocaleString()}`);
      lines.push(`  SL ${(rec.stop_loss || 0).toLocaleString()}  TP ${(rec.take_profit || 0).toLocaleString()}`);
    }
    lines.push('');
  }

  // Other positions
  const others = recommendations.filter(r => r.action !== 'BUY');
  if (others.length > 0) {
    lines.push('📋 Other Positions');
    for (const rec of others) {
      const actionEmoji = {
        'HOLD': '🔵',
        'REDUCE': '🟡',
        'SELL': '🔴',
        'WATCH': '👀'
      }[rec.action] || '·';

      lines.push(`  ${actionEmoji} ${rec.symbol} ${rec.action}  SL ${(rec.stop_loss || 0).toLocaleString()}`);
    }
    lines.push('');
  }

  // AI Analysis section
  if (aiAnalysis && aiAnalysis.generated && Object.keys(aiAnalysis.scores || {}).length > 0) {
    lines.push('🤖 AI Analysis');

    if (aiAnalysis.market_context) {
      lines.push(`_${aiAnalysis.market_context}_`);
      lines.push('');
    }

    const scores = aiAnalysis.scores || {};
    for (const rec of recommendations.slice(0, 5)) {
      const aiScore = scores[rec.symbol];
      if (aiScore) {
        const scoreBar = getScoreEmoji(aiScore.score);
        lines.push(`${rec.symbol} ${scoreBar} ${aiScore.score}/10`);

        if (aiScore.rationale) {
          lines.push(`  • ${aiScore.rationale}`);
        }

        if (aiScore.risk_note) {
          lines.push(`  ⚠ ${aiScore.risk_note}`);
        }
      }
    }

    const source = aiAnalysis.generated ? 'Powered by Gemini AI' : 'Using cached analysis';
    const analysisDate = aiAnalysis.analysis_date || new Date().toISOString().split('T')[0];
    lines.push(`\n_${source} | ${analysisDate}_`);
  }

  return lines.join('\n');
}

function getScoreEmoji(score) {
  if (score >= 8) return '🟢';
  if (score >= 6) return '🔵';
  if (score >= 4) return '🟡';
  return '🔴';
}

// GitHub API utilities
async function getFileContent(path, env) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}`;
  const response = await fetch(url, {
    headers: { 'Authorization': `token ${env.GITHUB_TOKEN}` }
  });

  if (response.status === 404) {
    throw new Error(`File not found: ${path}`);
  }

  if (!response.ok) {
    throw new Error(`GitHub API error: ${response.status}`);
  }

  const data = await response.json();
  const content = atob(data.content.replace(/\n/g, ''));
  return { content, sha: data.sha };
}

async function updateFile(path, content, sha, message, env) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/contents/${path}`;
  const body = {
    message: message,
    content: btoa(content),
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

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to update ${path}: ${response.status} ${error}`);
  }

  return await response.json();
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
    console.warn('Markdown failed, retrying without parse_mode');
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