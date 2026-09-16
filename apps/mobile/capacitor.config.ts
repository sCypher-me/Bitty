import type { CapacitorConfig } from "@capacitor/cli";

const productionUrl = process.env.BITTY_APP_URL?.replace(/\/$/, "");
const allowHttpLan = process.env.BITTY_ALLOW_HTTP_LAN === "true";
const isHttps = productionUrl?.startsWith("https://") ?? false;
const isExplicitLanHttp = Boolean(productionUrl?.startsWith("http://") && allowHttpLan);
if (productionUrl && !isHttps && !isExplicitLanHttp) {
  throw new Error("BITTY_APP_URL must use HTTPS, unless BITTY_ALLOW_HTTP_LAN=true is explicitly set for a trusted local network");
}
const productionHost = productionUrl ? new URL(productionUrl).hostname : undefined;

const config: CapacitorConfig = {
  appId: "com.julio.bitty",
  appName: "Bitty",
  webDir: "www",
  server: {
    ...(productionUrl ? { url: productionUrl } : {}),
    androidScheme: isExplicitLanHttp ? "http" : "https",
    cleartext: isExplicitLanHttp,
    allowNavigation: productionHost ? [productionHost] : ["*.ts.net"],
  },
  android: { buildOptions: { releaseType: "APK" } },
};

export default config;
