import type { CapacitorConfig } from "@capacitor/cli";

const productionUrl = process.env.BITTY_APP_URL?.replace(/\/$/, "");
if (productionUrl && !productionUrl.startsWith("https://")) {
  throw new Error("BITTY_APP_URL must use HTTPS");
}
const productionHost = productionUrl ? new URL(productionUrl).hostname : undefined;

const config: CapacitorConfig = {
  appId: "com.julio.bitty",
  appName: "Bitty",
  webDir: "www",
  server: {
    ...(productionUrl ? { url: productionUrl } : {}),
    androidScheme: "https",
    cleartext: false,
    allowNavigation: productionHost ? [productionHost] : ["*.ts.net"],
  },
  android: { buildOptions: { releaseType: "APK" } },
};

export default config;
