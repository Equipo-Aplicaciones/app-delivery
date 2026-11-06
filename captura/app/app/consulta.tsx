import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';
import { colors, fontFamily, fontSize, fontWeight, spacing } from '../src/constants/theme';

export default function ConsultaScreen() {
  return (
    <ScrollView contentContainerStyle={styles.page}>
      <View style={styles.header}>
        <Text style={styles.title}>Evidencia</Text>
        <Link href="/" style={styles.link}>
          Captura
        </Link>
      </View>
      <Text style={styles.body}>
        El teléfono solo envía la foto. La clave que permite leer y entregar la evidencia no va en la
        app: la usa el otro proyecto, en el header Authorization.
      </Text>
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
  body: {
    color: colors.text,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
  },
});
