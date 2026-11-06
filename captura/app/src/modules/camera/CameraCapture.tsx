import React, { useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { colors, fontFamily, fontSize, fontWeight, layout, radius, spacing } from '../../constants/theme';

type Props = {
  onCapture: (uri: string) => void;
};

function pickPictureSize(sizes: string[]): string | null {
  const parsed = sizes
    .map((label) => {
      const match = /^(\d+)x(\d+)$/.exec(label);
      if (!match) return null;
      const width = Number(match[1]);
      const height = Number(match[2]);
      return { label, long: Math.max(width, height) };
    })
    .filter((item): item is { label: string; long: number } => item !== null);
  const mid = parsed
    .filter((item) => item.long >= 1280 && item.long <= 1920)
    .sort((a, b) => b.long - a.long)[0];
  if (mid) return mid.label;
  const smaller = parsed.filter((item) => item.long < 1920).sort((a, b) => b.long - a.long)[0];
  return smaller?.label ?? parsed[0]?.label ?? null;
}

export function CameraCapture({ onCapture }: Props) {
  const cameraRef = useRef<CameraView>(null);
  const readyRef = useRef(false);
  const insets = useSafeAreaInsets();
  const [permission, requestPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pictureSize, setPictureSize] = useState<string | undefined>(undefined);
  const pickedSize = useRef(false);

  async function take() {
    if (!permission?.granted) {
      const next = await requestPermission();
      if (!next.granted) {
        setError('Sin permiso de cámara no se puede fotografiar el pedido.');
        return;
      }
    }
    if (!readyRef.current || !cameraRef.current) {
      setError('La cámara todavía no está lista.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const photo = await cameraRef.current.takePictureAsync({
        quality: 0.85,
        skipProcessing: true,
        shutterSound: false,
      });
      if (!photo?.uri) {
        setError('No se pudo capturar la foto.');
        return;
      }
      onCapture(photo.uri);
    } catch (err) {
      const detail = err instanceof Error ? err.message : '';
      setError(detail ? `No se pudo capturar la foto. ${detail}` : 'No se pudo capturar la foto.');
    } finally {
      setBusy(false);
    }
  }

  if (!permission || !permission.granted) {
    return (
      <View style={styles.permission}>
        <Text style={styles.error}>Sin permiso de cámara no se puede fotografiar el pedido.</Text>
        <Pressable onPress={() => void requestPermission()} style={styles.allow}>
          <Text style={styles.allowText}>Permitir cámara</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.fill}>
      <CameraView
        ref={cameraRef}
        style={styles.fill}
        facing="back"
        mode="picture"
        autofocus="on"
        animateShutter={false}
        pictureSize={pictureSize}
        active
        onCameraReady={() => {
          if (!pickedSize.current) {
            pickedSize.current = true;
            void cameraRef.current
              ?.getAvailablePictureSizesAsync()
              .then((sizes) => {
                const pick = pickPictureSize(sizes);
                if (pick) {
                  setPictureSize(pick);
                  return;
                }
                readyRef.current = true;
                setReady(true);
              })
              .catch(() => {
                readyRef.current = true;
                setReady(true);
              });
            return;
          }
          readyRef.current = true;
          setReady(true);
          setError('');
        }}
        onMountError={() => setError('No se pudo abrir la cámara.')}
      />
      <View style={[styles.controls, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
        {error ? <Text style={styles.errorOnCamera}>{error}</Text> : null}
        <Pressable
          disabled={!ready || busy}
          onPress={() => void take()}
          style={[styles.shutter, !ready || busy ? styles.shutterOff : null]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.text },
  permission: {
    flex: 1,
    backgroundColor: colors.background,
    justifyContent: 'center',
    padding: spacing.lg,
    gap: spacing.md,
  },
  controls: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: 'center',
    gap: spacing.sm,
    paddingTop: spacing.md,
  },
  shutter: {
    width: layout.shutter,
    height: layout.shutter,
    borderRadius: layout.shutter,
    backgroundColor: colors.surface,
    borderWidth: spacing.xs,
    borderColor: colors.accent,
  },
  shutterOff: { backgroundColor: colors.border },
  error: {
    color: colors.error,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
  },
  errorOnCamera: {
    color: colors.surface,
    backgroundColor: colors.error,
    fontFamily: fontFamily.base,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.bold,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    overflow: 'hidden',
  },
  allow: {
    minHeight: layout.touchMin,
    maxWidth: layout.ctaMaxWidth,
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  allowText: {
    color: colors.surface,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
    fontWeight: fontWeight.bold,
  },
});
