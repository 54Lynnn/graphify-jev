import { logger } from './logger';

async function processInbound(orgId: string, phone: string) {
    const { shouldHandle, processMessage } = await import('./mayaEngine.js');
    const handle = await shouldHandle(orgId, phone);
    if (handle.sessionId) {
        await processMessage({ orgId, phone }, handle.sessionId);
    }
}

async function pollMessages(orgId: string) {
    const { commsQueue } = await import('./queue.js');
    await commsQueue.add('check-inbound', { orgId });
}

function syncOnly() {
    logger.info('no dynamic imports here');
}

export { processInbound, pollMessages, syncOnly };
