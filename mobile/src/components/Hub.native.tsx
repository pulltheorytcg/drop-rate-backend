import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, BackHandler, Linking, Platform, Text, View } from "react-native";
import { WebView } from "react-native-webview";
import { SafeAreaView } from "react-native-safe-area-context";
import { HUB_ENTRY, isHubUrl, isExternalHttps } from "../lib/hub";
import { Button, C, styles } from "./ui";

// The actual hubs own login, authorization, scanning and business workflows.
// Never copy credentials between native code and the website or inject a role.
export default function Hub() {
  const web = useRef<WebView>(null);
  const canGoBack = useRef(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (Platform.OS !== "android") return;
    const handler = BackHandler.addEventListener("hardwareBackPress", () => {
      if (!canGoBack.current) return false;
      web.current?.goBack();
      return true;
    });
    return () => handler.remove();
  }, []);
  function openExternal(url: string) {
    if (isExternalHttps(url)) {
      void Linking.openURL(url).catch(() => setError("Unable to open this link."));
    }
  }
  return <SafeAreaView style={{flex: 1, backgroundColor: C.bg}}>
    {error ? <View style={styles.content}>
      <Text style={styles.section}>Unable to load your hub</Text>
      <Text style={styles.text}>{error}</Text>
      <Button title="Try again" onPress={() => {setError(""); setRevision(value => value + 1);}} />
      <Button title="Open in browser" secondary onPress={() => openExternal(HUB_ENTRY)} />
    </View> : <WebView
      key={revision}
      ref={web}
      source={{uri: HUB_ENTRY}}
      originWhitelist={["https://*"]}
      onShouldStartLoadWithRequest={request => {
        if (isHubUrl(request.url)) return true;
        openExternal(request.url);
        return false;
      }}
      onOpenWindow={event => openExternal(event.nativeEvent.targetUrl)}
      onNavigationStateChange={state => {canGoBack.current = state.canGoBack;}}
      onError={() => setError("Check your connection, then try again.")}
      onHttpError={event => {if (event.nativeEvent.statusCode >= 400) setError("The hub is temporarily unavailable.");}}
      onContentProcessDidTerminate={() => setError("The app needs to reload your hub.")}
      startInLoadingState
      renderLoading={() => <ActivityIndicator color={C.accent} style={{flex: 1}} />}
      mixedContentMode="never"
      allowFileAccess={false}
      allowsInlineMediaPlayback
      mediaCapturePermissionGrantType="prompt"
      webviewDebuggingEnabled={false}
      style={{flex: 1, backgroundColor: C.bg}}
    />}
  </SafeAreaView>;
}
