chrome.runtime.onInstalled.addListener(() => {
  console.log("Raven AI extension installed");
});

chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id });
});
