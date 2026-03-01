/**
 * Atomic Portfolio Operations for Cloudflare Worker
 *
 * Provides race-condition-safe portfolio state management with optimistic locking.
 * All money operations (buy, sell, setcash, dividend, fee) use this framework.
 */

// Configuration
const LOCK_TIMEOUT_MS = 60000; // 1 minute
const MAX_RETRY_ATTEMPTS = 5;
const RETRY_DELAY_BASE = 1000; // 1 second

/**
 * Acquire exclusive lock on portfolio state with exponential backoff retry
 */
async function acquireStateLock(lockId, operation, env) {
    for (let attempt = 1; attempt <= MAX_RETRY_ATTEMPTS; attempt++) {
        try {
            const { content, sha } = await getFileContent('data/portfolio_state.json', env);
            const state = JSON.parse(content);

            // Check if already locked by another operation
            if (state.lock && new Date(state.lock.expires_at) > new Date()) {
                if (attempt < MAX_RETRY_ATTEMPTS) {
                    const delay = RETRY_DELAY_BASE * Math.pow(2, attempt - 1);
                    console.log(`Lock held by ${state.lock.locked_by}, retrying in ${delay}ms (attempt ${attempt})`);
                    await sleep(delay);
                    continue;
                } else {
                    throw new Error(`Could not acquire lock after ${MAX_RETRY_ATTEMPTS} attempts. Lock held by: ${state.lock.locked_by}`);
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
    try {
        const { content, sha } = await getFileContent('data/portfolio_state.json', env);
        const state = JSON.parse(content);

        // Only release if we own the lock
        if (state.lock && state.lock.locked_by === lockId) {
            state.lock = null;
            await updateFile('data/portfolio_state.json', JSON.stringify(state, null, 2), sha, `Release lock: ${lockId}`, env);
            console.log(`Lock released by ${lockId}`);
        }
    } catch (error) {
        console.error(`Failed to release lock ${lockId}:`, error.message);
    }
}

/**
 * Universal handler for all money-related operations
 */
async function handleMoneyOperation(operationType, operationData, env) {
    const lockId = `worker_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const operation = `${operationType}_${JSON.stringify(operationData).slice(0, 50)}`;

    let lockAcquired = false;

    try {
        // 1. Acquire atomic lock
        const { state, originalSha } = await acquireStateLock(lockId, operation, env);
        lockAcquired = true;

        // 2. Validate operation (sufficient funds, valid data, etc.)
        validateMoneyOperation(state, operationType, operationData);

        // 3. Apply operation to state
        const newState = applyMoneyOperation(state, operationType, operationData);
        newState.sequence_number += 1;
        newState.last_updated = new Date().toISOString();
        newState.lock = null; // Release lock in new state

        // 4. Update state atomically
        await updateFile('data/portfolio_state.json', JSON.stringify(newState, null, 2), originalSha, `${operationType}: ${JSON.stringify(operationData)}`, env);

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
        console.error(`Money operation failed: ${operationType}`, error.message);

        // Release lock on error if we acquired it
        if (lockAcquired) {
            await releaseStateLock(lockId, env);
        }

        throw error;
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
    state.metadata.cash_adjustments = state.metadata.cash_adjustments || [];
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
            return `✅ Recorded BUY ${data.symbol}\\n` +
                   `Qty: ${data.qty.toLocaleString()} @ ${data.price.toLocaleString()}\\n` +
                   `Fee: ${(data.fee || 0).toLocaleString()} | Total: ${buyTotal.toLocaleString()}\\n` +
                   `Cash remaining: ${newState.cash.toLocaleString()}`;

        case 'sell':
            const sellTotal = data.price * data.qty - (data.fee || 0);
            return `✅ Recorded SELL ${data.symbol}\\n` +
                   `Qty: ${data.qty.toLocaleString()} @ ${data.price.toLocaleString()}\\n` +
                   `Fee: ${(data.fee || 0).toLocaleString()} | Total: ${sellTotal.toLocaleString()}\\n` +
                   `Cash balance: ${newState.cash.toLocaleString()}`;

        case 'setcash':
            return `💰 Cash balance set to ${data.amount.toLocaleString()} ₫`;

        case 'dividend':
            return `💰 Dividend recorded: ${data.symbol} +${data.amount.toLocaleString()} ₫\\n` +
                   `Cash balance: ${newState.cash.toLocaleString()}`;

        case 'fee':
            return `💸 Fee recorded: -${data.amount.toLocaleString()} ₫ (${data.note || 'manual fee'})\\n` +
                   `Cash balance: ${newState.cash.toLocaleString()}`;

        default:
            return `✅ Operation completed: ${operationType}`;
    }
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
        if (error.message.includes('404')) {
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

// Export the main function and utilities
export {
    handleMoneyOperation,
    acquireStateLock,
    releaseStateLock,
    validateMoneyOperation,
    applyMoneyOperation,
    formatOperationSuccess
};