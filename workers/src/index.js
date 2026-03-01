/**
 * Cloudflare Workers Command Gateway for IndicatorK Bot - Atomic State Version
 * Single-file implementation to avoid ES module import issues
 */

// Configuration
const LOCK_TIMEOUT_MS = 60000; // 1 minute
const MAX_RETRY_ATTEMPTS = 5;
const RETRY_DELAY_BASE = 1000; // 1 second

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

/**
 * Universal handler for all money-related operations (ATOMIC)
 */
async function handleMoneyOperation(operationType, operationData, env) {
    const maxRetries = 3;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {

        try {
            console.log(`Money operation attempt ${attempt}/${maxRetries}: ${operationType}`);

            // 1. Load current state and check for locks (NO COMMIT)
            const { content, sha } = await getFileContent('data/portfolio_state.json', env);
            const state = JSON.parse(content);

            // Check if locked by another operation (without acquiring our own lock)
            if (state.lock && new Date(state.lock.expires_at) > new Date()) {
                const timeLeft = Math.round((new Date(state.lock.expires_at) - new Date()) / 1000);
                throw new Error(`Operation in progress by ${state.lock.locked_by}, wait ${timeLeft}s`);
            }

            // 2. Validate operation (sufficient funds, valid data, etc.)
            validateMoneyOperation(state, operationType, operationData);

            // 3. Apply operation to state
            const newState = applyMoneyOperation(state, operationType, operationData);
            newState.sequence_number += 1;
            newState.last_updated = new Date().toISOString();
            newState.lock = null; // Ensure no lock in final state

            // 4. ATOMIC UPDATE - single commit for entire operation
            await updateFile('data/portfolio_state.json', JSON.stringify(newState, null, 2), sha, `${operationType}: ${JSON.stringify(operationData)}`, env);

            // 5. Log operation in audit trail
            await appendTradeLog({
                operation: operationType,
                source: 'worker',
                data: operationData,
                sequence_before: state.sequence_number,
                sequence_after: newState.sequence_number
            }, env);

            console.log(`Money operation completed: ${operationType}`, operationData);

            return {
                success: true,
                newState: newState,
                message: formatOperationSuccess(operationType, operationData, newState)
            };

        } catch (error) {
            console.error(`Money operation attempt ${attempt} failed: ${operationType}`, error.message);

            // Retry on 409 conflicts (SHA mismatch)
            if ((error.message.includes('409') || error.message.includes('conflict') || error.message.includes('does not match')) && attempt < maxRetries) {
                const delay = 1000 * attempt; // 1s, 2s, 3s delays
                console.log(`409 conflict detected, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries})`);
                await sleep(delay);
                continue;
            }

            // Non-retryable error or max retries exceeded
            throw error;
        }
    }

    throw new Error(`Failed after ${maxRetries} attempts due to repeated conflicts`);
}

/**
 * Acquire exclusive lock on portfolio state with exponential backoff retry
 */
async function acquireStateLock(lockId, operation, env) {
    for (let attempt = 1; attempt <= MAX_RETRY_ATTEMPTS; attempt++) {
        try {
            const { content, sha } = await getFileContent('data/portfolio_state.json', env);
            const state = JSON.parse(content);

            // Check if already locked by another operation
            if (state.lock) {
                const lockExpiry = new Date(state.lock.expires_at);
                const now = new Date();

                if (lockExpiry > now) {
                    // Lock is still active
                    if (attempt < MAX_RETRY_ATTEMPTS) {
                        const delay = RETRY_DELAY_BASE * Math.pow(2, attempt - 1);
                        const timeLeft = Math.round((lockExpiry - now) / 1000);
                        console.log(`Lock held by ${state.lock.locked_by}, expires in ${timeLeft}s, retrying in ${delay}ms (attempt ${attempt})`);
                        await sleep(delay);
                        continue;
                    } else {
                        throw new Error(`Could not acquire lock after ${MAX_RETRY_ATTEMPTS} attempts. Lock held by: ${state.lock.locked_by}`);
                    }
                } else {
                    // Lock has expired, clear it automatically
                    const expiredLockId = state.lock.locked_by;
                    console.log(`🕐 Clearing expired lock from ${expiredLockId} (expired ${Math.round((now - lockExpiry) / 1000)}s ago)`);
                    state.lock = null;
                    try {
                        await updateFile('data/portfolio_state.json', JSON.stringify(state, null, 2), sha, `Clear expired lock: ${expiredLockId}`, env);
                        console.log(`✅ Expired lock cleared automatically`);
                        // Continue to acquire our own lock below
                    } catch (expireError) {
                        console.log(`Failed to clear expired lock, will retry: ${expireError.message}`);
                        continue; // Retry the whole acquisition
                    }
                }
            }

            // Attempt to acquire lock
            const lockExpiry = new Date(Date.now() + LOCK_TIMEOUT_MS);
            state.lock = {
                locked_by: lockId,
                locked_at: new Date().toISOString(),
                expires_at: lockExpiry.toISOString(),
                operation: operation
            };

            // Atomic update - this will fail if another process updated the file
            await updateFile('data/portfolio_state.json', JSON.stringify(state, null, 2), sha, `Acquire lock: ${operation}`, env);

            console.log(`Lock acquired by ${lockId} for operation: ${operation}`);
            return { state, originalSha: sha };

        } catch (error) {
            if (error.message.includes('409') || error.message.includes('conflict')) {
                // Another process updated the file, retry
                if (attempt < MAX_RETRY_ATTEMPTS) {
                    const delay = RETRY_DELAY_BASE * Math.pow(2, attempt - 1);
                    console.log(`Lock acquisition conflict, retrying in ${delay}ms (attempt ${attempt})`);
                    await sleep(delay);
                    continue;
                }
            }
            throw new Error(`Failed to acquire lock: ${error.message}`);
        }
    }
}

/**
 * Release lock by clearing the lock field
 */
async function releaseStateLock(lockId, env) {
    // Retry lock release up to 3 times to prevent stuck locks
    for (let attempt = 1; attempt <= 3; attempt++) {
        try {
            const { content, sha } = await getFileContent('data/portfolio_state.json', env);
            const state = JSON.parse(content);

            // Only release if we own the lock
            if (state.lock && state.lock.locked_by === lockId) {
                state.lock = null;
                await updateFile('data/portfolio_state.json', JSON.stringify(state, null, 2), sha, `Release lock: ${lockId}`, env);
                console.log(`Lock released by ${lockId} (attempt ${attempt})`);
                return; // Success
            } else if (!state.lock) {
                console.log(`Lock ${lockId} already released`);
                return; // Already released
            } else {
                console.log(`Lock ${lockId} not owned by us, owned by: ${state.lock.locked_by}`);
                return; // Not our lock
            }
        } catch (error) {
            console.error(`Failed to release lock ${lockId} (attempt ${attempt}):`, error.message);

            if (attempt < 3) {
                const delay = 1000 * attempt; // 1s, 2s delays
                console.log(`Retrying lock release in ${delay}ms...`);
                await sleep(delay);
            } else {
                console.error(`❌ CRITICAL: Lock ${lockId} stuck after 3 release attempts. Lock will auto-expire in 1 minute.`);
            }
        }
    }
}

/**
 * Validation logic for different money operations
 */
function validateMoneyOperation(state, operationType, data) {
    switch(operationType) {
        case 'buy':
            const totalCost = data.price * data.qty + (data.fee || 0);
            if (state.cash < totalCost) {
                throw new Error(`Insufficient funds. Need: ${totalCost.toLocaleString()}, Available: ${state.cash.toLocaleString()}`);
            }
            if (data.qty <= 0 || data.price <= 0) {
                throw new Error('Quantity and price must be positive');
            }
            break;

        case 'sell':
            const position = state.positions[data.symbol];
            if (!position || position.qty < data.qty) {
                const available = position?.qty || 0;
                throw new Error(`Insufficient shares. Need: ${data.qty}, Available: ${available}`);
            }
            if (data.qty <= 0 || data.price <= 0) {
                throw new Error('Quantity and price must be positive');
            }
            break;

        case 'setcash':
            if (data.amount < 0) {
                throw new Error('Cash amount cannot be negative');
            }
            if (data.amount > 100_000_000_000) { // 100B VND sanity check
                throw new Error('Cash amount exceeds reasonable limit');
            }
            break;

        case 'dividend':
            if (!state.positions[data.symbol]) {
                throw new Error(`No position in ${data.symbol} for dividend`);
            }
            if (data.amount <= 0) {
                throw new Error('Dividend amount must be positive');
            }
            break;

        case 'fee':
            if (state.cash < data.amount) {
                throw new Error(`Insufficient cash for fee. Need: ${data.amount.toLocaleString()}, Available: ${state.cash.toLocaleString()}`);
            }
            if (data.amount <= 0) {
                throw new Error('Fee amount must be positive');
            }
            break;

        default:
            throw new Error(`Unknown operation type: ${operationType}`);
    }
}

/**
 * Apply specific money operations to portfolio state
 */
function applyMoneyOperation(state, operationType, data) {
    const newState = JSON.parse(JSON.stringify(state)); // Deep clone
    newState.metadata.last_operation = `${operationType}_${JSON.stringify(data)}`;
    newState.metadata.last_source = 'worker';

    switch(operationType) {
        case 'buy':
            return applyBuyOperation(newState, data);
        case 'sell':
            return applySellOperation(newState, data);
        case 'setcash':
            return applySetCashOperation(newState, data);
        case 'dividend':
            return applyDividendOperation(newState, data);
        case 'fee':
            return applyFeeOperation(newState, data);
        default:
            throw new Error(`Unknown money operation: ${operationType}`);
    }
}

function applyBuyOperation(state, data) {
    const totalCost = data.price * data.qty + (data.fee || 0);

    // Update cash
    state.cash -= totalCost;

    // Update position
    if (!state.positions[data.symbol]) {
        state.positions[data.symbol] = {
            symbol: data.symbol,
            asset_class: data.asset_class || 'stock',
            qty: 0,
            avg_cost: 0,
            current_price: data.price,
            unrealized_pnl: 0,
            realized_pnl: 0
        };
    }

    const pos = state.positions[data.symbol];
    const oldValue = pos.avg_cost * pos.qty;
    const newValue = data.price * data.qty;

    pos.qty += data.qty;
    pos.avg_cost = (oldValue + newValue) / pos.qty;
    pos.current_price = data.price;
    pos.unrealized_pnl = (pos.current_price - pos.avg_cost) * pos.qty;

    return state;
}

function applySellOperation(state, data) {
    const position = state.positions[data.symbol];
    const saleAmount = data.price * data.qty - (data.fee || 0);

    // Update cash
    state.cash += saleAmount;

    // Calculate realized P&L
    const realizedPnl = (data.price - position.avg_cost) * data.qty;
    position.realized_pnl += realizedPnl;
    state.total_realized_pnl += realizedPnl;

    // Update position
    position.qty -= data.qty;
    position.current_price = data.price;

    if (position.qty <= 0) {
        // Position closed
        delete state.positions[data.symbol];
    } else {
        position.unrealized_pnl = (position.current_price - position.avg_cost) * position.qty;
    }

    return state;
}

function applySetCashOperation(state, data) {
    const oldCash = state.cash;
    state.cash = data.amount;

    // Log cash adjustment in metadata
    if (!state.metadata.cash_adjustments) {
        state.metadata.cash_adjustments = [];
    }
    state.metadata.cash_adjustments.push({
        timestamp: new Date().toISOString(),
        from: oldCash,
        to: data.amount,
        difference: data.amount - oldCash,
        reason: data.reason || 'setcash_command'
    });

    return state;
}

function applyDividendOperation(state, data) {
    // Add dividend to cash
    state.cash += data.amount;

    // Add to position's realized PnL
    if (state.positions[data.symbol]) {
        state.positions[data.symbol].realized_pnl += data.amount;
    }

    // Track in total realized PnL
    state.total_realized_pnl += data.amount;

    return state;
}

function applyFeeOperation(state, data) {
    // Deduct fee from cash
    state.cash -= data.amount;

    // Track total fees in metadata
    state.metadata.total_fees = (state.metadata.total_fees || 0) + data.amount;

    return state;
}

/**
 * Format success messages for different operations
 */
function formatOperationSuccess(operationType, data, newState) {
    switch(operationType) {
        case 'buy':
            const buyTotal = data.price * data.qty + (data.fee || 0);
            return `✅ Recorded BUY ${data.symbol}\n` +
                   `Qty: ${data.qty.toLocaleString()} @ ${data.price.toLocaleString()}\n` +
                   `Fee: ${(data.fee || 0).toLocaleString()} | Total: ${buyTotal.toLocaleString()}\n` +
                   `Cash remaining: ${newState.cash.toLocaleString()}`;

        case 'sell':
            const sellTotal = data.price * data.qty - (data.fee || 0);
            return `✅ Recorded SELL ${data.symbol}\n` +
                   `Qty: ${data.qty.toLocaleString()} @ ${data.price.toLocaleString()}\n` +
                   `Fee: ${(data.fee || 0).toLocaleString()} | Total: ${sellTotal.toLocaleString()}\n` +
                   `Cash balance: ${newState.cash.toLocaleString()}`;

        case 'setcash':
            return `💰 Cash balance set to ${data.amount.toLocaleString()} ₫`;

        case 'dividend':
            return `💰 Dividend recorded: ${data.symbol} +${data.amount.toLocaleString()} ₫\n` +
                   `Cash balance: ${newState.cash.toLocaleString()}`;

        case 'fee':
            return `💸 Fee recorded: -${data.amount.toLocaleString()} ₫ (${data.note || 'manual fee'})\n` +
                   `Cash balance: ${newState.cash.toLocaleString()}`;

        default:
            return `✅ Operation completed: ${operationType}`;
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
  const response = await fetch(url, {
    headers: {
      'User-Agent': 'IndicatorK-Bot/2.0'
    }
  });
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
    headers: {
      'Authorization': `token ${env.GITHUB_TOKEN}`,
      'User-Agent': 'IndicatorK-Bot/2.0',
      'Accept': 'application/vnd.github.v3+json'
    }
  });

  if (response.status === 404) {
    throw new Error(`File not found: ${path}`);
  }

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`GitHub API error: ${response.status} - ${errorText.slice(0, 200)}`);
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
      'User-Agent': 'IndicatorK-Bot/2.0',
      'Content-Type': 'application/json',
      'Accept': 'application/vnd.github.v3+json'
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Failed to update ${path}: ${response.status} ${error}`);
  }

  return await response.json();
}

/**
 * Append operation to audit log
 */
async function appendTradeLog(logEntry, env) {
    const timestamp = new Date().toISOString();
    const auditEntry = {
        timestamp,
        operation: logEntry.operation,
        source: logEntry.source,
        data: logEntry.data,
        sequence_before: logEntry.sequence_before,
        sequence_after: logEntry.sequence_after,
        category: getOperationCategory(logEntry.operation)
    };

    const logLine = JSON.stringify(auditEntry) + '\n';
    await appendToFile('data/trades_log.jsonl', logLine, `Log: ${logEntry.operation}`, env);
}

function getOperationCategory(operation) {
    const categories = {
        'buy': 'trade',
        'sell': 'trade',
        'setcash': 'balance_adjustment',
        'dividend': 'income',
        'fee': 'expense'
    };
    return categories[operation] || 'unknown';
}

/**
 * Append content to a file (for audit logs)
 */
async function appendToFile(path, content, message, env) {
    try {
        const { content: existingContent, sha } = await getFileContent(path, env);
        const newContent = existingContent + content;
        await updateFile(path, newContent, sha, message, env);
    } catch (error) {
        if (error.message.includes('File not found')) {
            // File doesn't exist, create it
            await updateFile(path, content, null, `Create ${path}`, env);
        } else {
            throw error;
        }
    }
}

/**
 * Sleep utility for retry delays
 */
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
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