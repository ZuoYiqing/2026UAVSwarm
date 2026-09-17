export function createParentMessageHandler({ parentWindow, selfWindow, allowedOrigins, expectedOrigin, onSnapshot, onMode, onError }) {
  return event => {
    if (parentWindow === selfWindow || event.source !== parentWindow || !allowedOrigins.has(event.origin)) return false;
    if (expectedOrigin && event.origin !== expectedOrigin) return false;
    try {
      if (event.data?.type === "uav-swarm/vehicle-snapshot") onSnapshot(event.data.payload);
      else if (event.data?.type === "uav-swarm/use-demo") onMode("demo");
      else if (event.data?.type === "uav-swarm/use-live") onMode("live");
      else return false;
      return true;
    } catch (error) { onError(error); return false; }
  };
}
