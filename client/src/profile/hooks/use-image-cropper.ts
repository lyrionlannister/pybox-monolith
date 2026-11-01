import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { VIEW_SIZE, MIN_ZOOM, OUTPUT_SIZE } from "@/profile/constants/photo-cropper";
import { useUpdateProfilePhoto } from "./use-update-profile-photo";
import type { SelectedImage, Point } from "@/profile/types/profile-photo-page-types";

const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

const getBaseScale = (image: SelectedImage) => VIEW_SIZE / Math.min(image.width, image.height);

/**
 * Estado y lógica del editor de recorte de foto de perfil: selección de archivo,
 * zoom/arrastre dentro del marco circular, y generación del blob recortado a
 * OUTPUT_SIZE x OUTPUT_SIZE para subir.
 */
export const useImageCropper = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const dragRef = useRef<{ start: Point; origin: Point } | null>(null);
  const [sourceImage, setSourceImage] = useState<SelectedImage | null>(null);
  const [position, setPosition] = useState<Point>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(MIN_ZOOM);
  const [localError, setLocalError] = useState<string | null>(null);
  const { updateProfilePhoto, loading, error } = useUpdateProfilePhoto();

  useEffect(() => {
    return () => {
      if (sourceImage) URL.revokeObjectURL(sourceImage.url);
    };
  }, [sourceImage]);

  const metrics = useMemo(() => {
    if (!sourceImage) return null;
    const scale = getBaseScale(sourceImage) * zoom;
    const renderedWidth = sourceImage.width * scale;
    const renderedHeight = sourceImage.height * scale;
    const topLeftX = (VIEW_SIZE - renderedWidth) / 2 + position.x;
    const topLeftY = (VIEW_SIZE - renderedHeight) / 2 + position.y;
    return { scale, renderedWidth, renderedHeight, topLeftX, topLeftY };
  }, [sourceImage, position, zoom]);

  const clampPosition = (next: Point, nextZoom = zoom, image = sourceImage): Point => {
    if (!image) return { x: 0, y: 0 };
    const scale = getBaseScale(image) * nextZoom;
    const limitX = Math.max(0, (image.width * scale - VIEW_SIZE) / 2);
    const limitY = Math.max(0, (image.height * scale - VIEW_SIZE) / 2);
    return {
      x: clamp(next.x, -limitX, limitX),
      y: clamp(next.y, -limitY, limitY),
    };
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    if (!ACCEPTED_TYPES.has(file.type)) {
      setLocalError("Usa una imagen JPG, PNG o WebP.");
      return;
    }

    const url = URL.createObjectURL(file);
    const probe = new Image();
    probe.onload = () => {
      setSourceImage({
        url,
        name: file.name,
        size: file.size,
        width: probe.naturalWidth,
        height: probe.naturalHeight,
      });
      setZoom(MIN_ZOOM);
      setPosition({ x: 0, y: 0 });
      setLocalError(null);
    };
    probe.onerror = () => {
      URL.revokeObjectURL(url);
      setLocalError("No se pudo leer la imagen.");
    };
    probe.src = url;
  };

  const handleZoomChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextZoom = Number(event.target.value);
    setZoom(nextZoom);
    setPosition((current) => clampPosition(current, nextZoom));
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!sourceImage) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      start: { x: event.clientX, y: event.clientY },
      origin: position,
    };
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const next = {
      x: dragRef.current.origin.x + event.clientX - dragRef.current.start.x,
      y: dragRef.current.origin.y + event.clientY - dragRef.current.start.y,
    };
    setPosition(clampPosition(next));
  };

  const stopDragging = () => {
    dragRef.current = null;
  };

  const createCroppedBlob = () =>
    new Promise<Blob>((resolve, reject) => {
      if (!sourceImage || !metrics || !imageRef.current) {
        reject(new Error("Selecciona una foto antes de guardar."));
        return;
      }

      const canvas = document.createElement("canvas");
      canvas.width = OUTPUT_SIZE;
      canvas.height = OUTPUT_SIZE;
      const context = canvas.getContext("2d");
      if (!context) {
        reject(new Error("No se pudo preparar el recorte."));
        return;
      }

      const sourceX = Math.max(0, -metrics.topLeftX / metrics.scale);
      const sourceY = Math.max(0, -metrics.topLeftY / metrics.scale);
      const sourceSize = VIEW_SIZE / metrics.scale;
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = "high";
      context.drawImage(
        imageRef.current,
        sourceX,
        sourceY,
        sourceSize,
        sourceSize,
        0,
        0,
        OUTPUT_SIZE,
        OUTPUT_SIZE,
      );
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("No se pudo generar la imagen recortada."));
        }
      }, "image/png");
    });

  const handleSave = async () => {
    setLocalError(null);
    try {
      const blob = await createCroppedBlob();
      await updateProfilePhoto(blob);
      navigate("/profile");
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : "Error al guardar la foto.");
    }
  };

  const resetCrop = () => {
    setZoom(MIN_ZOOM);
    setPosition({ x: 0, y: 0 });
  };

  return {
    fileInputRef,
    imageRef,
    sourceImage,
    metrics,
    zoom,
    localError,
    error,
    loading,
    handleFileChange,
    handleZoomChange,
    handlePointerDown,
    handlePointerMove,
    stopDragging,
    handleSave,
    resetCrop,
  };
};
