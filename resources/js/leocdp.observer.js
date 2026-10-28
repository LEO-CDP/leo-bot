// Leo Observer SDK: load JavaScript code for [leo-bot]
(function () {
  // Data Source ID (from sys_data_source.data_source_id)
  window.leoC360DataSourceId = "ce8fd3f7-53ed-4633-81c7-1d210dccef87";

  // Default batch size of Event Tracking
  window.leoTrackingBatchSize = 10;

  // Tracking Log Domain and Endpoint URI
  window.leoObserverLogDomain = "beta.leocdp.com";
  var c360TrackingBase = "https://" + window.leoObserverLogDomain;
  window.leoTrackingEndpoint = c360TrackingBase + "/data/api/v1/tracking/logs";
  window.leoCdpProxyPath = "/data/cdp-sdk/html/cdp-event-proxy.html";

  // Data Touchpoint Metadata
  window.srcTouchpointName = encodeURIComponent(document.title);
  window.srcTouchpointUrl = encodeURIComponent(location.href);

  // Dynamic Loader for the Main Proxy CDP JS
  var src =
    "https://gcore.jsdelivr.net/gh/LEO-CDP/leo-customer360@main/customer360-event-api/static/c360-web-sdk/observer/leo.proxy.js".trim();
  if (src === "" || !/^(https?:)?\/\//i.test(src)) {
    src = c360TrackingBase + "/data/cdp-sdk/observer/leo.proxy.js";
  }
  var jsNode = document.createElement("script");
  jsNode.async = true;
  jsNode.defer = true;
  jsNode.src = src;
  var s = document.getElementsByTagName("script")[0];
  s.parentNode.insertBefore(jsNode, s);
})();

window.leoPendingLoginEvents = window.leoPendingLoginEvents || [];

// Leo Observer SDK is ready
function leoObserverProxyReady(session) {
  // auto tracking when CDP JS is ready
  if (
    window.LeoObserver &&
    typeof window.LeoObserver.recordEventPageView === "function"
  ) {
    window.LeoObserver.recordEventPageView();
  }

  var pendingLoginEvents = window.leoPendingLoginEvents.splice(0);
  pendingLoginEvents.forEach(trackEventLogin);
}

function trackEventLogin(eventObj) {
  var eventData = eventObj || {};
  if (
    !window.LeoObserver ||
    typeof window.LeoObserver.recordEventLogin !== "function"
  ) {
    window.leoPendingLoginEvents.push(eventData);
    return false;
  }

  window.LeoObserver.recordEventLogin(eventData);
  return true;
}

window.trackEventLogin = trackEventLogin;