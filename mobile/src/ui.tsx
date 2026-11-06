import React from 'react';
import {ActivityIndicator, Pressable, StyleSheet, Text, View} from 'react-native';

export const colors = {navy: '#13283c', ink: '#172b41', muted: '#65778b', background: '#f5f7fa', border: '#dfe7ee', green: '#147d64', pale: '#e5f5ee', red: '#aa303b'};
export function Button({title, onPress, disabled = false, secondary = false}: {title: string; onPress: () => void; disabled?: boolean; secondary?: boolean}): React.JSX.Element {
  return <Pressable accessibilityRole="button" accessibilityState={{disabled}} disabled={disabled} onPress={onPress} style={({pressed}) => [s.button, secondary && s.secondary, (disabled || pressed) && s.dim]}><Text style={[s.buttonText, secondary && s.secondaryText]}>{title}</Text></Pressable>;
}
export function Card({children}: {children: React.ReactNode}): React.JSX.Element {return <View style={s.card}>{children}</View>;}
export function Notice({text, error = false}: {text: string; error?: boolean}): React.JSX.Element | null {
  return text ? <Text accessibilityRole={error ? 'alert' : undefined} accessibilityLiveRegion="polite" style={[s.notice, error && s.error]}>{text}</Text> : null;
}
export function Loading({text = 'Загрузка…'}: {text?: string}): React.JSX.Element {return <View style={s.row}><ActivityIndicator color={colors.green}/><Text style={s.muted}>{text}</Text></View>;}
export const s = StyleSheet.create({
  root: {flex: 1, backgroundColor: colors.background},
  imagePreview: {width: '100%', height: 240},
  content: {padding: 20, gap: 16, paddingBottom: 36},
  header: {backgroundColor: colors.navy, paddingHorizontal: 20, paddingVertical: 22, gap: 8},
  brand: {color: '#e4effa', fontSize: 24, fontWeight: '700'},
  eyebrow: {color: '#9ab0c2', fontSize: 11, letterSpacing: 2},
  title: {color: colors.ink, fontSize: 28, fontWeight: '700'},
  heading: {color: colors.ink, fontSize: 18, fontWeight: '600'},
  text: {color: colors.ink, fontSize: 15, lineHeight: 22},
  muted: {color: colors.muted, fontSize: 13, lineHeight: 20},
  card: {backgroundColor: '#fff', borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 18, gap: 14},
  label: {color: colors.ink, fontSize: 13, fontWeight: '500'},
  input: {borderWidth: 1, borderColor: '#bdcbd7', borderRadius: 8, color: colors.ink, backgroundColor: '#fff', padding: 12, minHeight: 48, fontSize: 16},
  button: {backgroundColor: colors.green, minHeight: 48, padding: 12, borderRadius: 8, alignItems: 'center', justifyContent: 'center'},
  buttonText: {color: '#fff', fontSize: 14, fontWeight: '600', textAlign: 'center'},
  secondary: {backgroundColor: '#edf2f6', borderColor: colors.border, borderWidth: 1},
  secondaryText: {color: colors.ink},
  dim: {opacity: 0.5},
  notice: {color: colors.green, backgroundColor: colors.pale, padding: 12, borderRadius: 8, fontSize: 14, lineHeight: 21},
  error: {color: colors.red, backgroundColor: '#fff0f1'},
  row: {flexDirection: 'row', alignItems: 'center', gap: 12, flexWrap: 'wrap'},
  badge: {color: colors.green, backgroundColor: colors.pale, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6, fontSize: 12, alignSelf: 'flex-start'},
  divider: {height: 1, backgroundColor: colors.border},
});
