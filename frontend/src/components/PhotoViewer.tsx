import { useEffect, useState } from "react";
import {
  Dimensions,
  FlatList,
  Image,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { GestureDetector, Gesture, GestureHandlerRootView } from "react-native-gesture-handler";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { Ionicons } from "@expo/vector-icons";

/**
 * SignalMar — fullscreen photo viewer with pinch-to-zoom + horizontal swipe.
 *
 * Phase D. Used by the report detail screen when the user taps a thumbnail.
 * Built on top of `react-native-gesture-handler` + `react-native-reanimated`
 * (both already in the project) so it works in Expo Go without native
 * modules.
 *
 * Keeps the pan + zoom state per-photo via index — swiping moves to the
 * neighbouring photo, then resets scale on swipe complete.
 */
export interface PhotoViewerProps {
  visible: boolean;
  photos: string[];
  initialIndex: number;
  onClose: () => void;
}

const { width: W, height: H } = Dimensions.get("window");

function ZoomablePhoto({ uri }: { uri: string }) {
  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const tx = useSharedValue(0);
  const ty = useSharedValue(0);
  const sx = useSharedValue(0);
  const sy = useSharedValue(0);

  const pinch = Gesture.Pinch()
    .onUpdate((e) => {
      scale.value = Math.max(1, Math.min(5, savedScale.value * e.scale));
    })
    .onEnd(() => {
      savedScale.value = scale.value;
      if (scale.value < 1.05) {
        scale.value = withTiming(1);
        tx.value = withTiming(0);
        ty.value = withTiming(0);
        savedScale.value = 1;
        sx.value = 0; sy.value = 0;
      }
    });

  const pan = Gesture.Pan()
    .averageTouches(true)
    .onUpdate((e) => {
      if (scale.value > 1) {
        tx.value = sx.value + e.translationX;
        ty.value = sy.value + e.translationY;
      }
    })
    .onEnd(() => {
      sx.value = tx.value;
      sy.value = ty.value;
    });

  const doubleTap = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd(() => {
      if (scale.value > 1) {
        scale.value = withTiming(1);
        tx.value = withTiming(0);
        ty.value = withTiming(0);
        savedScale.value = 1;
        sx.value = 0; sy.value = 0;
      } else {
        scale.value = withTiming(2.5);
        savedScale.value = 2.5;
      }
    });

  const composed = Gesture.Simultaneous(pinch, pan, doubleTap);

  const animStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: tx.value },
      { translateY: ty.value },
      { scale: scale.value },
    ],
  }));

  return (
    <GestureDetector gesture={composed}>
      <Animated.View style={[styles.slide, animStyle]}>
        <Image source={{ uri }} style={styles.img} resizeMode="contain" />
      </Animated.View>
    </GestureDetector>
  );
}

export function PhotoViewer({ visible, photos, initialIndex, onClose }: PhotoViewerProps) {
  const [index, setIndex] = useState(initialIndex);
  useEffect(() => {
    if (visible) setIndex(Math.max(0, Math.min(initialIndex, photos.length - 1)));
  }, [visible, initialIndex, photos.length]);

  if (!visible || photos.length === 0) return null;

  return (
    <Modal
      visible={visible}
      onRequestClose={onClose}
      animationType="fade"
      transparent={Platform.OS === "ios"}
      statusBarTranslucent
    >
      <GestureHandlerRootView style={{ flex: 1, backgroundColor: "#000" }}>
        <View style={styles.root} testID="photo-viewer">
          <FlatList
            data={photos}
            horizontal
            pagingEnabled
            keyExtractor={(_, i) => String(i)}
            initialScrollIndex={index}
            getItemLayout={(_, i) => ({ length: W, offset: W * i, index: i })}
            onMomentumScrollEnd={(e) => {
              const i = Math.round(e.nativeEvent.contentOffset.x / W);
              setIndex(i);
            }}
            renderItem={({ item }) => <ZoomablePhoto uri={item} />}
            showsHorizontalScrollIndicator={false}
          />
          <Pressable style={styles.closeBtn} onPress={onClose} testID="photo-viewer-close">
            <Ionicons name="close" size={26} color="#fff" />
          </Pressable>
          {photos.length > 1 && (
            <View style={styles.counter}>
              <Text style={styles.counterText}>{index + 1} / {photos.length}</Text>
            </View>
          )}
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#000", justifyContent: "center" },
  slide: { width: W, height: H, alignItems: "center", justifyContent: "center" },
  img: { width: W, height: H },
  closeBtn: {
    position: "absolute", top: 40, right: 16,
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.2)",
  },
  counter: {
    position: "absolute", bottom: 40, alignSelf: "center",
    paddingHorizontal: 14, paddingVertical: 6, borderRadius: 16,
    backgroundColor: "rgba(0,0,0,0.55)",
  },
  counterText: { color: "#fff", fontWeight: "700", fontSize: 13 },
});
