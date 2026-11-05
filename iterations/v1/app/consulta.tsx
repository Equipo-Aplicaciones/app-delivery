import React, { useState } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';
import { colors, fontFamily, fontSize, fontWeight, layout, radius, spacing } from '../src/constants/theme';
import { prepareLookup, type Aggregator } from '../src/engine';
import { AggregatorPicker } from '../src/modules/aggregator/AggregatorPicker';
import { pedir, readEvidenceConfig, type EvidenceImage } from '../src/modules/evidence-api';
import { OrderNumberField } from '../src/modules/order-name/OrderNumberField';

type Phase = 'idle' | 'loading' | 'success' | 'empty' | 'error';

export default function ConsultaScreen() {
  const [order, setOrder] = useState('');
  const [aggregator, setAggregator] = useState<Aggregator | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState('');
  const [images, setImages] = useState<EvidenceImage[]>([]);

  const keyReady = prepareLookup({ order, aggregator });

  async function onAsk() {
    const prepared = prepareLookup({ order, aggregator });
    if (!prepared.ok) {
      setPhase('error');
      setMessage(prepared.error);
      setImages([]);
      return;
    }
    setPhase('loading');
    setMessage('');
    const result = await pedir(readEvidenceConfig(), {
      agregador: prepared.key.agregador,
      numeroOrden: prepared.key.numeroOrden,
    });
    if (!result.ok) {
      setPhase('error');
      setMessage(result.error);
      setImages([]);
      return;
    }
    setImages(result.data.images);
    if (result.data.images.length === 0) {
      setPhase('empty');
      setMessage('No hay evidencia para esa clave');
      return;
    }
    setPhase('success');
  }

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <View style={styles.header}>
        <Text style={styles.title}>Traer imagen</Text>
        <Link href="/" style={styles.link}>
          Captura
        </Link>
      </View>
      <OrderNumberField value={order} onChange={setOrder} />
      <AggregatorPicker value={aggregator} onChange={setAggregator} />
      <Pressable
        disabled={phase === 'loading' || !keyReady.ok}
        onPress={() => void onAsk()}
        style={[styles.send, phase !== 'loading' && keyReady.ok ? styles.sendOn : styles.sendOff]}
      >
        <Text style={styles.sendText}>{phase === 'loading' ? 'Buscando…' : 'Pedir evidencia'}</Text>
      </Pressable>
      {phase === 'empty' ? <Text style={styles.muted}>{message}</Text> : null}
      {phase === 'error' ? <Text style={styles.err}>{message}</Text> : null}
      {images.map((image) => (
        <View key={image.id} style={styles.card}>
          <Image source={{ uri: image.url }} style={styles.photo} />
          <Text style={styles.muted}>{image.createdAt}</Text>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: {
    backgroundColor: colors.background,
    padding: spacing.md,
    gap: spacing.md,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: {
    color: colors.text,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
  },
  link: {
    color: colors.accent,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
  },
  send: {
    minHeight: layout.touchMin,
    maxWidth: layout.ctaMaxWidth,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  sendOn: { backgroundColor: colors.accent },
  sendOff: { backgroundColor: colors.border },
  sendText: {
    color: colors.surface,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
  },
  muted: {
    color: colors.textMuted,
    fontFamily: fontFamily.base,
    fontSize: fontSize.sm,
  },
  err: { color: colors.error, fontFamily: fontFamily.base, fontSize: fontSize.sm },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.sm,
    gap: spacing.sm,
  },
  photo: { height: 180, borderRadius: radius.sm, backgroundColor: colors.background },
});
