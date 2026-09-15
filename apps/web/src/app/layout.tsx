import type {Metadata,Viewport} from "next"; import "./globals.css"; import {Providers} from "@/components/providers";
export const metadata:Metadata={title:"Bitty",description:"Automação pessoal de cripto em reais, com controles de risco",applicationName:"Bitty",icons:{icon:"/bitty-icon.svg"}};
export const viewport:Viewport={themeColor:"#080b16",width:"device-width",initialScale:1,viewportFit:"cover"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="pt-BR"><body><Providers>{children}</Providers></body></html>}
