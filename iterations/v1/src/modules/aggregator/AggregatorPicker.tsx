import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, fontFamily, fontSize, fontWeight, layout, radius, spacing } from '../../constants/theme';
import { AGGREGATORS, aggregatorLabel, type Aggregator } from '../../engine/aggregator';

type Props = {
  value: Aggregator | null;
  onChange: (value: Aggregator) => void;
};

export function AggregatorPicker({ value, onChange }: Props) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>Agregador</Text>
      <View style={styles.row}>
        {AGGREGATORS.map((item) => {
          const selected = item === value;
          return (
            <Pressable
              key={item}
              onPress={() => onChange(item)}
              style={[styles.choice, selected ? styles.choiceOn : styles.choiceOff]}
            >
              <Text style={[styles.choiceText, selected ? styles.choiceTextOn : styles.choiceTextOff]}>
                {aggregatorLabel(item)}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  label: {
    color: colors.text,
    fontFamily: fontFamily.base,
    fontSize: fontSize.md,
  },
  row: { flexDirection: 'row', gap: spacing.sm },
  choice: {
    minHeight: layout.touchMin,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
  choiceOn: { backgroundColor: colors.accent, borderColor: colors.accent },
  choiceOff: { backgroundColor: colors.surface, borderColor: colors.border },
  choiceText: { fontFamily: fontFamily.base, fontSize: fontSize.md },
  choiceTextOn: { color: colors.surface, fontWeight: fontWeight.bold },
  choiceTextOff: { color: colors.text, fontWeight: fontWeight.regular },
});
