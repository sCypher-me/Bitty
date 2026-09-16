# Bitty no Android

O backend de produção é a fonte de verdade: nele ficam API, banco centralizado, motor e credenciais criptografadas. Android e web são somente clientes da mesma instância e mantêm sessões independentes, sem copiar chaves da corretora para o aparelho.

## Uso local provisório

1. Inicie o Bitty com `powershell -ExecutionPolicy Bypass -File scripts/start-bitty.ps1`.
2. Instale Tailscale no notebook e no Android e conecte ambos à mesma conta.
3. Publique somente a porta web `3000` com HTTPS privado pelo Tailscale Serve. Não exponha as portas `3000` ou `8000` diretamente à internet.
4. Abra o endereço HTTPS do notebook no Chrome Android e escolha **Adicionar à tela inicial**.

O manifesto e o service worker já estão incluídos. O proxy web encaminha `/api/v1` internamente para a API, portanto o celular acessa uma única origem e o login funciona com cookie seguro.

## APK de produção

O projeto nativo fica em `apps/mobile/android`. O build sem `BITTY_APP_URL` abre o conector Tailscale local; ele é apenas provisório. O APK final deve receber exatamente o domínio HTTPS da Vercel já validado.

Para reconstruir:

```powershell
cd apps/mobile
$env:BITTY_APP_URL="https://<dominio-validado>.vercel.app"
pnpm android:sync
cd android
$env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
$env:ANDROID_HOME="$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_USER_HOME="$env:USERPROFILE\.android"
$env:GRADLE_USER_HOME="$env:USERPROFILE\.gradle"
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

O APK de teste é criado em `apps/mobile/android/app/build/outputs/apk/debug/app-debug.apk`. Ele bloqueia HTTP aberto e restringe a navegação ao host configurado. Para uso permanente, gere e proteja fora do Git uma chave de assinatura de release. Não declare o APK pronto antes de testar login, refresh, logout, Paper Bot e sincronização contra produção em aparelho/emulador.

## Modo notebook na mesma rede Wi-Fi

Para operar sem hospedagem paga, o notebook pode ser o servidor central. Inicie o Bitty expondo somente o frontend na rede local:

```powershell
.\scripts\start-bitty.ps1 -LanAddress 192.168.1.3
```

Gere o APK apontando explicitamente para o endereço privado do notebook:

```powershell
.\scripts\build-lan-apk.ps1 -LanAddress 192.168.1.3
```

O arquivo será criado em `outputs/Bitty-LAN-debug.apk`. O celular precisa estar na mesma rede Wi-Fi e o endereço do notebook deve permanecer estável. HTTP sem TLS é permitido somente neste build LAN explícito; builds públicos continuam exigindo HTTPS.

Esse APK LAN destina-se exclusivamente ao Paper Bot em uma rede doméstica confiável. Não digite senha reutilizada nem credenciais do Mercado Bitcoin pelo celular enquanto a conexão for HTTP. Cadastre credenciais somente pelo próprio notebook em `http://127.0.0.1:3000`; para uso remoto ou financeiro no Android, configure primeiro uma origem HTTPS privada, como Tailscale Serve.
