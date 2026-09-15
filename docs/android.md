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
