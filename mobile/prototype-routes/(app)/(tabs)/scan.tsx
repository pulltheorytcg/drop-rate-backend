import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Image, Linking, Pressable, Text, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as ImagePicker from "expo-image-picker";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import { randomUUID } from "expo-crypto";
import { useFocusEffect } from "expo-router";
import { useSession } from "../../../lib/session";
import { captureSize } from "../../../lib/capture";
import { errorMessage } from "../../../lib/api";
import {
  cataloguePath,
  intakePayload,
  selectCandidate,
  selectSearch,
} from "../../../lib/workflows";
import type {
  Card,
  Candidate,
  PendingIntake,
  Recognition,
  Selection,
} from "../../../lib/types";
import {
  Page,
  Panel,
  Button,
  Field,
  CardRow,
  Notice,
  styles,
  C,
} from "../../../components/ui";
export default function Scan() {
  const { api, access, demo } = useSession();
  const [permission, requestPermission] = useCameraPermissions();
  const camera = useRef<CameraView>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [torch, setTorch] = useState(false);
  const [photo, setPhoto] = useState<{ uri: string; data: string } | null>(
    null,
  );
  const [result, setResult] = useState<Recognition | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [matches, setMatches] = useState<Card[]>([]);
  const [condition, setCondition] = useState("");
  const [seal, setSeal] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState<PendingIntake | null>(null);
  useFocusEffect(
    useCallback(() => {
      void api
        .pending()
        .then(setPending)
        .catch((e) => setError(errorMessage(e)));
      return () => {
        setCameraOpen(false);
        setCameraReady(false);
      };
    }, [api]),
  );
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state !== "active") {
        setCameraOpen(false);
        setCameraReady(false);
      }
    });
    return () => sub.remove();
  }, []);
  async function run(work: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }
  function clearReview() {
    setResult(null);
    setSelected(null);
    setMatches([]);
    setConfirmed(false);
    setCondition("");
    setSeal("");
  }
  async function prepare(uri: string, width: number, height: number) {
    const context = ImageManipulator.manipulate(uri);
    const size = captureSize(width, height);
    if (size.width !== width || size.height !== height) context.resize(size);
    const rendered = await context.renderAsync();
    const image = await rendered.saveAsync({
      format: SaveFormat.JPEG,
      compress: 0.82,
      base64: true,
    });
    if (!image.base64 || image.base64.length > 10_000_000)
      throw new Error(
        "This photo is too large. Try a closer, lower-resolution image.",
      );
    clearReview();
    setPhoto({
      uri: image.uri,
      data: "data:image/jpeg;base64," + image.base64,
    });
    setCameraOpen(false);
  }
  const openCamera = () =>
    run(async () => {
      if (pending)
        throw new Error(
          "Finish your pending save before scanning another item.",
        );
      const p = permission?.granted ? permission : await requestPermission();
      if (!p.granted)
        throw new Error(
          "Camera access is needed to take a photo. You can choose an existing photo or enable the camera in Settings.",
        );
      setCameraReady(false);
      setCameraOpen(true);
    });
  const choosePhoto = () =>
    run(async () => {
      if (pending) throw new Error("Finish your pending save first.");
      const pick = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        quality: 1,
        allowsMultipleSelection: false,
      });
      if (!pick.canceled)
        await prepare(
          pick.assets[0].uri,
          pick.assets[0].width,
          pick.assets[0].height,
        );
    });
  const capture = () =>
    run(async () => {
      const image = await camera.current?.takePictureAsync({
        quality: 0.85,
        skipProcessing: false,
      });
      if (!image)
        throw new Error("The camera did not return a photo. Please try again.");
      await prepare(image.uri, image.width, image.height);
    });
  const identify = () =>
    run(async () => {
      if (pending) throw new Error("Finish your pending save first.");
      if (!photo && !demo) return;
      clearReview();
      const response = await api.request<Recognition>(
        "/api/v1/recognition/resolve",
        "POST",
        { image_data_url: photo?.data || "data:image/jpeg;base64,demo-only" },
      );
      setResult(response);
      if (response.run.status === "FAILED")
        setError(
          "Recognition could not complete. Retake the photo before saving an item.",
        );
    });
  const chooseCandidate = (candidate: Candidate) =>
    run(async () => {
      if (!result) return;
      setSelected(await selectCandidate(api, result, candidate));
      setConfirmed(false);
      setCondition("");
      setSeal("");
    });
  const find = () =>
    run(async () => {
      if (search.trim().length < 2)
        throw new Error("Enter at least two characters.");
      const response = await api.request<{ items: Card[] }>(
        cataloguePath(access!, search, result || undefined),
      );
      setMatches(response.items);
      if (!response.items.length)
        setMessage("No exact printing found. Try the card number or set name.");
    });
  const chooseSearch = (card: Card) =>
    run(async () => {
      if (!result) return;
      setSelected(await selectSearch(api, result, card));
      setConfirmed(false);
      setCondition("");
      setSeal("");
    });
  const save = () =>
    run(async () => {
      if (!result || !selected || !confirmed)
        throw new Error("Review and confirm the exact printing first.");
      if (result.run.status === "FAILED")
        throw new Error(
          "Retake the photo to start a completed recognition run before intake.",
        );
      const sealed = selected.card.product_type === "SEALED";
      if (sealed ? !seal : !condition)
        throw new Error("Choose the physical condition before saving.");
      if (await api.pending())
        throw new Error("Finish your pending save first.");
      await api.request(
        `/api/v1/recognition/runs/${result.run.id}/feedback`,
        "POST",
        {
          outcome: selected.outcome,
          selected_catalogue_id: selected.catalogueId,
          notes: "Explicit human review in PullTheory mobile.",
        },
      );
      try {
        const response = await api.queueIntake(
          intakePayload(access!, result, selected, condition, seal),
          randomUUID(),
          selected.card.name,
        );
        setMessage(
          `Draft saved${response.inventory?.inventory_code ? " · " + response.inventory.inventory_code : ""}. It still needs operational review.`,
        );
        setPhoto(null);
        clearReview();
      } finally {
        setPending(await api.pending());
      }
    });
  const resume = () =>
    run(async () => {
      try {
        await api.resumeIntake();
        setPhoto(null);
        clearReview();
        setMessage("Your draft save has been recovered.");
      } finally {
        setPending(await api.pending());
      }
    });
  if (cameraOpen)
    return (
      <View style={{ flex: 1, backgroundColor: "#000" }}>
        <CameraView
          ref={camera}
          style={{ flex: 1 }}
          facing="back"
          enableTorch={torch}
          onCameraReady={() => setCameraReady(true)}
          onMountError={() => {
            setCameraOpen(false);
            setError("Camera unavailable. Try choosing a photo.");
          }}
        >
          <View
            pointerEvents="none"
            style={{
              flex: 1,
              justifyContent: "center",
              alignItems: "center",
              padding: 35,
            }}
          >
            <Text style={{ color: "#fff", marginBottom: 24 }}>
              Keep the full card or product in the frame
            </Text>
            <View
              style={{
                width: "85%",
                maxWidth: 310,
                aspectRatio: 0.72,
                borderColor: C.accent,
                borderWidth: 2,
                borderRadius: 18,
              }}
            />
            <Text style={{ color: "#fff", marginTop: 24 }}>
              Use even light. Avoid glare.
            </Text>
          </View>
        </CameraView>
        <View style={{ padding: 18, gap: 10 }}>
          <Button
            title="Capture photo"
            icon="camera"
            busy={busy}
            disabled={!cameraReady}
            onPress={() => void capture()}
          />
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Button
                title={torch ? "Flashlight off" : "Flashlight on"}
                secondary
                onPress={() => setTorch(!torch)}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Button
                title="Cancel"
                secondary
                disabled={busy}
                onPress={() => setCameraOpen(false)}
              />
            </View>
          </View>
        </View>
      </View>
    );
  const sealed = selected?.card.product_type === "SEALED";
  return (
    <Page>
      <View>
        <Text style={styles.eyebrow}>CAPTURE · MATCH · REVIEW</Text>
        <Text style={styles.title}>Find your next match.</Text>
        <Text style={styles.muted}>
          Raw cards and sealed products. One physical item at a time.
        </Text>
      </View>
      <Notice error>{error}</Notice>
      <Notice>{message}</Notice>
      {pending ? (
        <Panel>
          <Text style={styles.section}>A save needs your attention</Text>
          <Text style={styles.muted}>
            {pending.title}. Retry the original request before starting another
            item.
          </Text>
          <Button
            title="Recover pending save"
            onPress={() => void resume()}
            busy={busy}
          />
        </Panel>
      ) : (
        <>
          <Panel>
            {photo ? (
              <Image
                source={{ uri: photo.uri }}
                accessibilityLabel="Photo selected for recognition"
                style={{ height: 280, width: "100%", borderRadius: 12 }}
                resizeMode="contain"
              />
            ) : (
              <View
                style={{
                  height: 190,
                  borderWidth: 1,
                  borderColor: C.line,
                  borderStyle: "dashed",
                  borderRadius: 12,
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 12,
                }}
              >
                <Text style={{ fontSize: 42, color: C.accent }}>⌗</Text>
                <Text style={styles.text}>Every card has a story.</Text>
                <Text style={styles.small}>Start with a clear photograph.</Text>
              </View>
            )}
            <Button
              title={photo ? "Retake photo" : "Open camera"}
              icon="camera-outline"
              onPress={() => void openCamera()}
              busy={busy}
            />
            <Button
              title="Choose a photo"
              secondary
              icon="images-outline"
              onPress={() => void choosePhoto()}
              disabled={busy}
            />
            {permission?.status === "denied" && !permission.canAskAgain && (
              <Button
                title="Open camera settings"
                secondary
                onPress={() =>
                  void Linking.openSettings().catch((e) =>
                    setError(errorMessage(e)),
                  )
                }
              />
            )}
            <Text style={styles.small}>
              By choosing Identify, you send this photo to PullTheory’s
              recognition service. Check the result before adding a draft.
            </Text>
            {(photo || demo) && (
              <Button
                title={
                  demo && !photo
                    ? "Try a sample recognition"
                    : "Identify this item"
                }
                onPress={() => void identify()}
                busy={busy}
              />
            )}
          </Panel>
          {result && (
            <>
              <Text style={styles.section}>Review possible matches</Text>
              <Text style={styles.muted}>
                Compare the set, number, language and variant with the item in
                your hand.
              </Text>
              {result.candidates
                .filter((c) => !c.hard_rejected)
                .map((candidate) => (
                  <Panel key={candidate.id}>
                    <CardRow
                      card={candidate.candidate_snapshot}
                      subtitle={
                        candidate.catalogue_id
                          ? "Catalogue match"
                          : "New reference — needs review"
                      }
                    />
                    <Button
                      title={
                        candidate.catalogue_id
                          ? "Review this match"
                          : "Add printing for review"
                      }
                      secondary
                      onPress={() => void chooseCandidate(candidate)}
                      disabled={
                        busy ||
                        result.run.status === "FAILED" ||
                        (!candidate.catalogue_id &&
                          candidate.candidate_snapshot.product_type ===
                            "SEALED")
                      }
                    />
                    {!candidate.catalogue_id &&
                      candidate.candidate_snapshot.product_type ===
                        "SEALED" && (
                        <Text style={styles.small}>
                          This new sealed identity needs catalogue review before
                          intake.
                        </Text>
                      )}
                  </Panel>
                ))}
              {!result.candidates.some((c) => !c.hard_rejected) && (
                <Notice>
                  No usable match. Search for the exact printing below.
                </Notice>
              )}
              <Panel>
                <Text style={styles.section}>Find another printing</Text>
                <Field
                  label="Search name, card number or set"
                  value={search}
                  onChangeText={setSearch}
                  maxLength={80}
                  onSubmitEditing={() => void find()}
                />
                <Button
                  title="Search catalogue"
                  secondary
                  onPress={() => void find()}
                  busy={busy}
                />
                {matches.map((card, index) => (
                  <View key={card.id || card.provider_id || index}>
                    <CardRow card={card} />
                    <Button
                      title={
                        card.requires_materialization
                          ? "Add reference and review"
                          : "Review this printing"
                      }
                      secondary
                      disabled={busy}
                      onPress={() => void chooseSearch(card)}
                    />
                  </View>
                ))}
              </Panel>
            </>
          )}
          {selected && (
            <Panel style={{ borderColor: C.accent }}>
              <Text style={styles.eyebrow}>YOUR SELECTED PRINTING</Text>
              <CardRow card={selected.card} />
              <Text style={styles.section}>
                {sealed ? "Seal status" : "Physical condition"}
              </Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
                {(sealed
                  ? ["SEALED", "UNSEALED"]
                  : ["NM", "LP", "MP", "HP", "DMG"]
                ).map((value) => (
                  <Pressable
                    key={value}
                    accessibilityRole="button"
                    accessibilityState={{
                      selected: (sealed ? seal : condition) === value,
                    }}
                    disabled={busy}
                    onPress={() =>
                      sealed ? setSeal(value) : setCondition(value)
                    }
                    style={{
                      padding: 14,
                      borderRadius: 12,
                      backgroundColor:
                        (sealed ? seal : condition) === value ? C.accent : C.bg,
                    }}
                  >
                    <Text
                      style={{
                        color:
                          (sealed ? seal : condition) === value
                            ? C.onAccent
                            : C.text,
                      }}
                    >
                      {value}
                    </Text>
                  </Pressable>
                ))}
              </View>
              {!sealed && (
                <Text style={styles.small}>
                  NM: near mint · LP: lightly played · MP: moderately played ·
                  HP: heavily played · DMG: damaged. Slabs require the graded
                  intake flow in the web portal.
                </Text>
              )}
              <Pressable
                accessibilityRole="checkbox"
                accessibilityState={{ checked: confirmed }}
                disabled={busy}
                onPress={() => setConfirmed(!confirmed)}
                style={[styles.row, { paddingVertical: 12 }]}
              >
                <Text style={{ fontSize: 24, color: C.accent }}>
                  {confirmed ? "☑" : "☐"}
                </Text>
                <Text style={{ ...styles.text, flex: 1 }}>
                  I checked the exact printing, language and physical condition.
                </Text>
              </Pressable>
              <Button
                title="Save physical item as draft"
                icon="add-circle-outline"
                onPress={() => void save()}
                busy={busy}
                disabled={
                  !confirmed ||
                  !(sealed ? seal : condition) ||
                  result?.run.status === "FAILED"
                }
              />
              <Text style={styles.small}>
                This creates one draft owned by {access!.display_name}. It does
                not approve identity or publish the item for sale.
              </Text>
            </Panel>
          )}
        </>
      )}
    </Page>
  );
}
