import React, { useState } from "react";
import {
  View,
  Text,
  Pressable,
  TextInput,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  Image,
  type TextInputProps,
  type StyleProp,
  type ViewStyle,
  RefreshControl,
} from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import type { Card } from "../lib/types";
// Shared browser palette: owner-portal.css and founder-workspace.css.
export const C = {
  bg: "#F4F7FB",
  panel: "#FFFFFF",
  line: "#E2E8F0",
  text: "#13223B",
  muted: "#5C6F87",
  accent: "#0B7187",
  onAccent: "#FFFFFF",
  navy: "#071B3F",
  cyan: "#28D7EB",
  soft: "#EEF3F8",
  info: "#EAF7FA",
  danger: "#B52E37",
  dangerSoft: "#FFF0F1",
};
export const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: C.bg },
  content: {
    padding: 22,
    gap: 20,
    width: "100%",
    maxWidth: 760,
    alignSelf: "center",
    paddingBottom: 35,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  spread: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  title: { color: C.text, fontSize: 30, fontWeight: "700", letterSpacing: -1 },
  text: { color: C.text, fontSize: 16, lineHeight: 24 },
  muted: { color: C.muted, fontSize: 14, lineHeight: 21 },
  small: { color: C.muted, fontSize: 12, lineHeight: 18 },
  panel: {
    backgroundColor: C.panel,
    borderWidth: 1,
    borderColor: C.line,
    borderRadius: 12,
    padding: 18,
    gap: 12,
  },
  section: { color: C.text, fontSize: 19, fontWeight: "600" },
  input: {
    borderWidth: 1,
    borderColor: C.line,
    backgroundColor: "#F8FAFC",
    color: C.text,
    padding: 14,
    borderRadius: 11,
    minHeight: 50,
    fontSize: 16,
  },
  badge: {
    alignSelf: "flex-start",
    paddingVertical: 5,
    paddingHorizontal: 9,
    borderRadius: 7,
    backgroundColor: C.info,
  },
  eyebrow: {
    color: C.accent,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  divider: { height: 1, backgroundColor: C.line },
  button: {
    minHeight: 50,
    borderRadius: 12,
    padding: 14,
    justifyContent: "center",
    alignItems: "center",
    flexDirection: "row",
    gap: 8,
  },
  error: { color: C.danger, lineHeight: 22 },
  metric: {
    fontSize: 29,
    fontWeight: "700",
    color: C.text,
    letterSpacing: -0.8,
  },
});
export function Page({
  children,
  refreshing,
  onRefresh,
}: {
  children: React.ReactNode;
  refreshing?: boolean;
  onRefresh?: () => void;
}) {
  return (
    <ScrollView
      style={styles.page}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh ? (
          <RefreshControl
            refreshing={!!refreshing}
            onRefresh={onRefresh}
            tintColor={C.accent}
          />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  );
}
export function Panel({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return <View style={[styles.panel, style]}>{children}</View>;
}
export function Button({
  title,
  onPress,
  busy,
  disabled,
  secondary,
  icon,
}: {
  title: string;
  onPress: () => void;
  busy?: boolean;
  disabled?: boolean;
  secondary?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled: !!disabled || !!busy }}
      onPress={onPress}
      disabled={disabled || busy}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: secondary ? C.panel : C.accent,
          borderWidth: 1,
          borderColor: secondary ? C.line : C.accent,
          opacity: disabled || busy ? 0.55 : pressed ? 0.8 : 1,
        },
      ]}
    >
      {busy ? (
        <ActivityIndicator color={secondary ? C.text : C.onAccent} />
      ) : (
        icon && (
          <Ionicons
            name={icon}
            size={19}
            color={secondary ? C.text : C.onAccent}
          />
        )
      )}
      <Text
        style={{
          color: secondary ? C.text : C.onAccent,
          fontSize: 15,
          fontWeight: "700",
        }}
      >
        {title}
      </Text>
    </Pressable>
  );
}
export function Field({ label, ...props }: TextInputProps & { label: string }) {
  return (
    <View style={{ gap: 7 }}>
      <Text style={styles.muted}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={C.muted}
        style={styles.input}
        {...props}
      />
    </View>
  );
}
export function Notice({
  children,
  error,
}: {
  children?: React.ReactNode;
  error?: boolean;
}) {
  if (!children) return null;
  return (
    <View
      accessibilityRole={error ? "alert" : undefined}
      style={{
        backgroundColor: error ? C.dangerSoft : C.info,
        padding: 14,
        borderRadius: 12,
      }}
    >
      <Text style={error ? styles.error : { ...styles.muted, color: C.accent }}>
        {children}
      </Text>
    </View>
  );
}
export function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <Panel>
      <Ionicons name="albums-outline" size={30} color={C.muted} />
      <Text style={styles.section}>{title}</Text>
      <Text style={styles.muted}>{detail}</Text>
    </Panel>
  );
}
export function CardArt({ card, size = 74 }: { card: Card; size?: number }) {
  const [failed, setFailed] = useState(false);
  const uri = card.image_url;
  return (
    <View
      style={{
        width: size,
        height: size * 1.36,
        backgroundColor: C.soft,
        borderRadius: 10,
        overflow: "hidden",
        borderWidth: 1,
        borderColor: C.line,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {uri?.startsWith("https://") && !failed ? (
        <Image
          accessibilityLabel={card.name}
          source={{ uri }}
          onError={() => setFailed(true)}
          style={{ width: "100%", height: "100%" }}
          resizeMode="contain"
        />
      ) : (
        <>
          <Ionicons name="layers-outline" size={size * 0.32} color={C.accent} />
          <Text
            style={{
              color: C.accent,
              fontSize: 9,
              marginTop: 8,
              textAlign: "center",
            }}
          >
            {card.game || "PULLTHEORY"}
          </Text>
        </>
      )}
    </View>
  );
}
export function CardRow({
  card,
  subtitle,
  trailing,
  onPress,
}: {
  card: Card;
  subtitle?: string;
  trailing?: string;
  onPress?: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? "button" : undefined}
      style={[styles.row, { paddingVertical: 10, alignItems: "flex-start" }]}
    >
      <CardArt card={card} />
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={{ ...styles.text, fontWeight: "600" }}>{card.name}</Text>
        <Text style={styles.small}>
          {[card.set_name, card.card_number].filter(Boolean).join(" · ")}
        </Text>
        <Text style={styles.small}>
          {[card.language, card.variant].filter(Boolean).join(" · ")}
        </Text>
        {subtitle && (
          <Text style={{ ...styles.small, color: C.accent }}>{subtitle}</Text>
        )}
        {trailing && (
          <Text style={{ ...styles.text, fontWeight: "600" }}>{trailing}</Text>
        )}
      </View>
      {onPress && <Ionicons name="chevron-forward" size={18} color={C.muted} />}
    </Pressable>
  );
}
