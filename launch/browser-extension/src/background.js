// Background service worker — minimal. Most logic lives in the content
// script. The service worker handles install/update events and exposes
// an alarm-based periodic refresh in case we add background polling
// later.

chrome.runtime.onInstalled.addListener((details) => {
    if (details.reason === 'install') {
        console.log('Synapse PR Conflict Watcher installed');
        // Open the popup once so users configure the endpoint
        chrome.action.openPopup?.();
    }
});
