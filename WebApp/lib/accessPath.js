export const WEBAPP_PORT = Number(process.env.REVNEST_WEBAPP_PORT || process.env.PORT || 3000);
export const MOCKHOTEL_PORT = Number(process.env.MOCKHOTEL_PORT || 3001);

function trimTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function defaultHostUrl(port) {
  return `http://localhost:${port}`;
}

function defaultSandboxUrl(port) {
  return `http://host.openshell.internal:${port}`;
}

export function getAccessPathInfo() {
  const webAppHostUrl = trimTrailingSlash(process.env.REVNEST_WEBAPP_HOST_URL || defaultHostUrl(WEBAPP_PORT));
  const webAppPublicUrl = trimTrailingSlash(process.env.REVNEST_WEBAPP_PUBLIC_URL || webAppHostUrl);
  const webAppSandboxUrl = trimTrailingSlash(process.env.REVNEST_WEBAPP_SANDBOX_URL || defaultSandboxUrl(WEBAPP_PORT));
  const mockHotelHostUrl = trimTrailingSlash(process.env.MOCKHOTEL_HOST_URL || defaultHostUrl(MOCKHOTEL_PORT));
  const mockHotelSandboxUrl = trimTrailingSlash(
    process.env.MOCKHOTEL_SANDBOX_URL || defaultSandboxUrl(MOCKHOTEL_PORT)
  );

  return {
    webApp: {
      port: WEBAPP_PORT,
      humanUrl: webAppPublicUrl,
      hostUrl: webAppHostUrl,
      sandboxUrl: webAppSandboxUrl,
    },
    mockHotel: {
      port: MOCKHOTEL_PORT,
      humanUrl: mockHotelHostUrl,
      hostUrl: mockHotelHostUrl,
      sandboxUrl: mockHotelSandboxUrl,
      readOnlyAgentApi: `${mockHotelSandboxUrl}/api/agent/current-prices`,
    },
    notes: [
      "Use webApp.humanUrl from your normal browser.",
      "Inside NemoClaw/OpenShell, localhost is the sandbox itself; use host.openshell.internal for host services.",
      "Revy must not call WebApp accept APIs from the sandbox. Human approval must happen in the WebApp browser session.",
    ],
  };
}
