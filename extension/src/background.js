chrome.runtime.onInstalled.addListener(() => {
  console.log("Raven extension installed");
});

chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id });
});
