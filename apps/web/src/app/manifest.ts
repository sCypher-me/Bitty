import type {MetadataRoute} from "next";

export default function manifest():MetadataRoute.Manifest{return {
  name:"Bitty — Automação de cripto",
  short_name:"Bitty",
  description:"Painel pessoal de automação de cripto em reais.",
  start_url:"/",
  display:"standalone",
  background_color:"#080b16",
  theme_color:"#7c5cff",
  orientation:"portrait-primary",
  icons:[{src:"/bitty-icon.svg",sizes:"any",type:"image/svg+xml",purpose:"maskable"}],
};}
