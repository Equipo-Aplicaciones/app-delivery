import React, { useState } from 'react';
import { Image, KeyboardAvoidingView, Pressable, StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { colors, fontFamily, fontSize, fontWeight, layout, radius, spacing } from '../src/constants/theme';
import { prepareSend, type Aggregator } from '../src/engine';
import { AggregatorPicker } from '../src/modules/aggregator/AggregatorPicker';
import { CameraCapture } from '../src/modules/camera/CameraCapture';
import { enviar, readEvidenceConfig } from '../src/modules/evidence-api';
import { OrderNumberField } from '../src/modules/order-name/OrderNumberField';

type Phase = 'idle' | 'loading' | 'success' | 'error';

export default function CapturaScreen() {
  const insets = useSafeAreaInsets();
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [order, setOrder] = useState('');
  const [aggregator, setAggregator] = useState<Aggregator | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState('');
  const [notice, setNotice] = useState('');

  const ready = prepareSend({ imageUri, order, aggregator });

  function retake() {
    setImageUri(null);
    setOrder('');
    setAggregator(null);
    setPhase('idle');
    setMessage('');
  }

  async function onSend() {
    const prepared = prepareSend({ imageUri, order, aggregator });
    if (!prepared.ok) {
      setPhase('error');
      setMessage(prepared.error);
      return;
    }
    setPhase('loading');
    setMessage('');
    const result = await enviar(readEvidenceConfig(), prepared.payload);
    if (!result.ok) {
      setPhase('error');
      setMessage(result.error);
      return;
    }
    setNotice('La imagen quedó guardada');
    retake();
  }

  if (!imageUri) {
    return (
      <View style={styles.fill}>
        <CameraCapture onCapture={setImageUri} />
        <View style={[styles.topBar, { paddingTop: Math.max(insets.top, spacing.md) }]}>
          {notice ? <Text style={styles.notice}>{notice}</Text> : <View />}
          <Link href="/consulta" style={styles.link}>
            Traer
          </Link>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.fill}>
      <Image source={{ uri: imageUri }} style={styles.fill} resizeMode="cover" />
      <KeyboardAvoidingView behavior="padding" style={styles.sheetWrap}>
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Rotular</Text>
            <Pressable onPress={retake} hitSlop={spacing.sm}>
              <Text style={styles.linkDark}>Otra foto</Text>
            </Pressable>
          </View>
          <OrderNumberField value={order} onChange={setOrder} />
          <AggregatorPicker value={aggregator} onChange={setAggregator} />
          <Pressable
            disabled={!ready.ok || phase === 'loading'}
            onPress={() => void onSend()}
            style={[styles.send, ready.ok && phase !== 'loading' ? styles.sendOn : styles.sendOff]}
          >
            <Text style={styles.sendText}>{phase === 'loading' ? 'Enviando…' : 'Enviar'}</Text>
          </Pressable>
          {phase === 'error' ? <Text style={styles.err}>{message}</Text> : null}
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.text },
  topBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    paddingHorizontal: spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  link: {
    color: colors.surface,
    backgroundColor: colors.accent,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
    overflow: 'hidden',
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  notice: {
    color: colors.text,
    backgroundColor: colors.surface,
    fontFamily: fontFamily.base,
    fontSize: fontSize.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    overflow: 'hidden',
  },
  sheetWrap: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.md,
    borderTopRightRadius: radius.md,
    padding: spacing.md,
    gap: spacing.md,
  },
  sheetHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  sheetTitle: {
    color: colors.text,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
  },
  linkDark: {
    color: colors.accent,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
  },
  send: {
    minHeight: layout.touchMin,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendOn: { backgroundColor: colors.accent },
  sendOff: { backgroundColor: colors.border },
  sendText: {
    color: colors.surface,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
  },
  err: { color: colors.error, fontFamily: fontFamily.base, fontSize: fontSize.sm },
});
