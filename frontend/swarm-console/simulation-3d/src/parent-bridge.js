export function createParentMessageHandler({ parentWindow, selfWindow, allowedOrigins, expectedOrigin, onSnapshot, onMode, onError, onSelectVehicle }) {
  return event => {
    if (parentWindow === selfWindow || event.source !== parentWindow || !allowedOrigins.has(event.origin)) return false;
    if (expectedOrigin && event.origin !== expectedOrigin) return false;
    try {
      if (event.data?.type === "uav-swarm/vehicle-snapshot") onSnapshot(event.data.payload);
      else if (event.data?.type === "uav-swarm/use-demo") onMode("demo");
      else if (event.data?.type === "uav-swarm/use-live") onMode("live");
      else if (event.data?.type === "uav-swarm/select-vehicle") {
        // 父页面（主控制台的节点列表）切换了选中载具。
        // 调用方必须以 notifyParent=false 的方式应用，否则两侧会互相触发形成环路。
        if (typeof onSelectVehicle === "function") onSelectVehicle(event.data.payload?.nodeId ?? null);
        else return false;
      } else return false;
      return true;
    } catch (error) { onError(error); return false; }
  };
}
