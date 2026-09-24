"use client";

/**
 * UserMessageCard — 用户消息（回放时从 rollout 映射）。
 *
 * 右对齐气泡布局：头像 + 内容靠右，内容包裹在灰色圆角矩形背景中。
 * 使用 Markdown 渲染：用户可能输入代码块、LaTeX 或 markdown 格式文本。
 * 显示时间戳（如果可用）。
 */

import type { UserMessageItem } from "@/shared/types/api";
import {
  ChevronLeft,
  ChevronRight,
  File,
  Maximize2,
  MessageSquareText,
  Scan,
  User,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Markdown } from "./Markdown";
import { formatItemTime } from "@/shared/lib/utils/format";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLanguage } from "@/shared/components/i18n/LanguageProvider";
import { parseBrowserCommentDisplay } from "@/shared/lib/codex/user-message";

interface Props {
  item: UserMessageItem;
  /** item 时间戳（ISO 字符串） */
  timestamp?: string;
}

export function UserMessageCard({ item, timestamp }: Props) {
  const { t } = useLanguage();
  const [activeImage, setActiveImage] = useState<number | null>(null);
  const images = item.images ?? [];
  const attachments = (item.attachments ?? []).filter(
    (attachment) => images.length === 0 || !/\.(?:png|jpe?g|gif|webp)$/i.test(attachment.name),
  );
  const hasText = item.text.trim().length > 0;
  const browserComment = parseBrowserCommentDisplay(item.text);

  useEffect(() => {
    if (activeImage === null) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActiveImage(null);
      if (event.key === "ArrowLeft" && images.length > 1) {
        setActiveImage((current) => current === null ? null : (current - 1 + images.length) % images.length);
      }
      if (event.key === "ArrowRight" && images.length > 1) {
        setActiveImage((current) => current === null ? null : (current + 1) % images.length);
      }
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [activeImage, images.length]);

  return (
    <div className="timeline-item flex flex-row-reverse gap-3 px-2 py-1.5">
      {/* 头像 */}
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[hsl(var(--overlay)/0.1)] bg-[hsl(var(--overlay)/0.05)]">
        <User className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
      </div>
      {/* 气泡内容：靠右对齐，最大宽度限制 80% */}
      <div className="flex w-full max-w-[80%] min-w-0 flex-col items-end">
        {/* 头部：you + 时间戳 */}
        <div className="mb-1 flex items-center gap-2">
          {timestamp && (
            <span
              className="text-xs text-[hsl(var(--muted-foreground))]"
              title={new Date(timestamp).toString()}
            >
              {formatItemTime(timestamp)}
            </span>
          )}
          <span className="text-sm font-semibold text-foreground">
            you
          </span>
        </div>
        {/* 附件独立于正文气泡，以紧凑缩略样式展示 */}
        {(images.length > 0 || attachments.length > 0) && (
          <div className="mb-2 flex max-w-full flex-wrap justify-end gap-2" aria-label={t("image.messageImages")}>
            {images.map((src, index) => (
              <button
                key={`${item.id}-thumbnail-${index}`}
                type="button"
                onClick={() => setActiveImage(index)}
                className="group/image relative h-20 w-28 shrink-0 overflow-hidden rounded-lg border border-[hsl(var(--overlay)/0.12)] bg-[hsl(var(--surface-2))] shadow-sm transition hover:-translate-y-0.5 hover:border-[hsl(var(--primary)/0.45)] hover:shadow-md focus-ring sm:h-24 sm:w-36"
                aria-label={`放大查看浏览器批注截图 ${index + 1}`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={src}
                  alt={`浏览器批注截图 ${index + 1}`}
                  loading="lazy"
                  className="h-full w-full object-cover object-top transition-transform duration-200 group-hover/image:scale-[1.025]"
                />
                <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-white opacity-0 transition group-hover/image:bg-black/25 group-hover/image:opacity-100 group-focus-visible/image:bg-black/25 group-focus-visible/image:opacity-100">
                  <Maximize2 className="h-5 w-5 drop-shadow" />
                </span>
                {images.length > 1 && (
                  <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[9px] text-white">
                    {index + 1}/{images.length}
                  </span>
                )}
              </button>
            ))}
            {attachments.map((attachment) => (
              <div
                key={`${item.id}-attachment-${attachment.path}`}
                title={attachment.path}
                className="flex h-14 max-w-64 items-center gap-2.5 rounded-lg border border-[hsl(var(--overlay)/0.12)] bg-[hsl(var(--surface-2))] px-3 shadow-sm"
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--overlay)/0.07)] text-[hsl(var(--muted-foreground))]">
                  <File className="h-4 w-4" />
                </span>
                <span className="min-w-0 text-left">
                  <span className="block truncate text-xs font-medium text-foreground/85">
                    {attachment.name}
                  </span>
                  <span className="block truncate font-mono text-[9px] text-[hsl(var(--muted-foreground))]">
                    {attachment.path}
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}

        {/* 灰色圆角矩形背景仅包裹正文 */}
        {hasText && (
          <div className="w-full min-w-0 overflow-hidden rounded-xl bg-[hsl(var(--overlay)/0.06)] px-3.5 py-[8px] text-sm text-foreground/90">
            {browserComment ? (
              <div className="py-0.5">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground/80">
                  <MessageSquareText className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                  {t("browserComments.title")}
                </div>
                <ol className="mt-2 space-y-1.5">
                  {browserComment.comments.map((comment, index) => (
                    <li key={`${item.id}-browser-comment-${index}`} className="flex items-start gap-2 leading-6">
                      <span className="mt-1 flex h-4 min-w-4 items-center justify-center rounded bg-[hsl(var(--overlay)/0.07)] px-1 font-mono text-[9px] text-[hsl(var(--muted-foreground))]">
                        {index + 1}
                      </span>
                      <span className="min-w-0 flex-1">{comment}</span>
                    </li>
                  ))}
                </ol>
                {browserComment.request && (
                  <div className="mt-2.5 border-t border-[hsl(var(--overlay)/0.08)] pt-2">
                    <span className="font-mono text-[9px] uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                      {t("browserComments.request")}
                    </span>
                    <Markdown className="text-sm prose-p:my-1">{browserComment.request}</Markdown>
                  </div>
                )}
              </div>
            ) : (
              <Markdown className="prose-p:my-0 prose-p:leading-6">{item.text}</Markdown>
            )}
          </div>
        )}
      </div>

      {activeImage !== null && images[activeImage] && createPortal(
        <ImageLightbox
          images={images}
          activeIndex={activeImage}
          onChange={setActiveImage}
          onClose={() => setActiveImage(null)}
        />,
        document.body,
      )}
    </div>
  );
}

interface ImageLightboxProps {
  images: string[];
  activeIndex: number;
  onChange: (index: number) => void;
  onClose: () => void;
}

function ImageLightbox({ images, activeIndex, onChange, onClose }: ImageLightboxProps) {
  const { t } = useLanguage();
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [zoom, setZoom] = useState(100);
  const [isFit, setIsFit] = useState(true);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ pointerId: number; startX: number; startY: number; panX: number; panY: number } | null>(null);

  const renderedWidth = naturalSize ? naturalSize.width * zoom / 100 : 0;
  const renderedHeight = naturalSize ? naturalSize.height * zoom / 100 : 0;
  const maxPanX = Math.max(0, (renderedWidth - canvasSize.width) / 2);
  const maxPanY = Math.max(0, (renderedHeight - canvasSize.height) / 2);
  const canPan = maxPanX > 0 || maxPanY > 0;
  const clampPan = useCallback((nextPan: { x: number; y: number }) => ({
    x: Math.max(-maxPanX, Math.min(maxPanX, nextPan.x)),
    y: Math.max(-maxPanY, Math.min(maxPanY, nextPan.y)),
  }), [maxPanX, maxPanY]);

  const fitToViewport = useCallback((size = naturalSize) => {
    if (!size) return;
    const availableWidth = Math.max(1, window.innerWidth - 48);
    const availableHeight = Math.max(1, window.innerHeight - 112);
    const fittedZoom = Math.min(
      100,
      (availableWidth / size.width) * 100,
      (availableHeight / size.height) * 100,
    );
    setZoom(Math.max(10, fittedZoom));
    setPan({ x: 0, y: 0 });
    setIsFit(true);
  }, [naturalSize]);

  useEffect(() => {
    setNaturalSize(null);
    setZoom(100);
    setPan({ x: 0, y: 0 });
    setIsDragging(false);
    drag.current = null;
    setIsFit(true);
  }, [activeIndex]);

  useEffect(() => {
    const refit = () => {
      const bounds = canvasRef.current?.getBoundingClientRect();
      if (bounds) setCanvasSize({ width: bounds.width, height: bounds.height });
      if (isFit) fitToViewport();
    };
    refit();
    window.addEventListener("resize", refit);
    return () => window.removeEventListener("resize", refit);
  }, [fitToViewport, isFit]);

  useEffect(() => {
    setPan((currentPan) => {
      const nextPan = clampPan(currentPan);
      return nextPan.x === currentPan.x && nextPan.y === currentPan.y ? currentPan : nextPan;
    });
    if (!canPan) {
      drag.current = null;
      setIsDragging(false);
    }
  }, [canPan, clampPan]);

  const setManualZoom = (nextZoom: number) => {
    setZoom(Math.min(400, Math.max(10, nextZoom)));
    setIsFit(false);
  };

  const zoomWithWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    setZoom((current) => Math.min(400, Math.max(10, current * Math.exp(-event.deltaY * 0.0015))));
    setIsFit(false);
  };

  const startDrag = (event: React.PointerEvent<HTMLImageElement>) => {
    if (event.button !== 0 || !canPan) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      panX: pan.x,
      panY: pan.y,
    };
    setIsDragging(true);
  };

  const moveDrag = (event: React.PointerEvent<HTMLImageElement>) => {
    const currentDrag = drag.current;
    if (!currentDrag || currentDrag.pointerId !== event.pointerId) return;
    setPan(clampPan({
      x: currentDrag.panX + event.clientX - currentDrag.startX,
      y: currentDrag.panY + event.clientY - currentDrag.startY,
    }));
  };

  const endDrag = (event: React.PointerEvent<HTMLImageElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    setIsDragging(false);
  };

  const previousImage = () => onChange((activeIndex - 1 + images.length) % images.length);
  const nextImage = () => onChange((activeIndex + 1) % images.length);

  return (
    <div
      className="fixed inset-0 z-[9999] bg-black/90 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`浏览器批注截图 ${activeIndex + 1}`}
      data-image-lightbox="true"
      onMouseDown={onClose}
    >
      <div
        className="absolute left-1/2 top-3 z-20 flex -translate-x-1/2 items-center gap-1 rounded-xl border border-white/15 bg-black/75 p-1.5 text-white shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          onClick={() => setManualZoom(zoom - 25)}
          disabled={zoom <= 10}
          className="flex h-8 w-8 items-center justify-center rounded-lg transition hover:bg-white/15 disabled:opacity-35 focus-ring"
          aria-label={t("image.zoomOut")}
          title={t("image.zoomOut")}
        >
          <ZoomOut className="h-4 w-4" />
        </button>
        <span className="w-14 text-center font-mono text-xs tabular-nums" aria-label="当前放大率">
          {Math.round(zoom)}%
        </span>
        <button
          type="button"
          onClick={() => setManualZoom(zoom + 25)}
          disabled={zoom >= 400}
          className="flex h-8 w-8 items-center justify-center rounded-lg transition hover:bg-white/15 disabled:opacity-35 focus-ring"
          aria-label={t("image.zoomIn")}
          title={t("image.zoomIn")}
        >
          <ZoomIn className="h-4 w-4" />
        </button>
        <div className="mx-1 h-5 w-px bg-white/15" />
        <button
          type="button"
          onClick={() => fitToViewport()}
          className={`flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs transition hover:bg-white/15 focus-ring ${isFit ? "bg-white/15" : ""}`}
          aria-label={t("image.fit")}
        >
          <Scan className="h-4 w-4" />
          {t("image.fit")}
        </button>
        <button
          type="button"
          onClick={() => setManualZoom(100)}
          className="flex h-8 items-center rounded-lg px-2.5 font-mono text-xs transition hover:bg-white/15 focus-ring"
          aria-label={t("image.actual")}
        >
          100%
        </button>
        <div className="mx-1 h-5 w-px bg-white/15" />
        <button
          type="button"
          onClick={onClose}
          className="flex h-8 w-8 items-center justify-center rounded-lg transition hover:bg-white/15 focus-ring"
          aria-label={t("image.close")}
          title={`${t("image.close")} (Esc)`}
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div
        ref={canvasRef}
        className="absolute inset-4 overflow-hidden"
        onWheel={zoomWithWheel}
        aria-label="图片预览画布：滚轮缩放，左键拖动"
      >
        <div className="flex h-full w-full items-center justify-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={images[activeIndex]}
            alt={`放大的浏览器批注截图 ${activeIndex + 1}`}
            draggable={false}
            onMouseDown={(event) => event.stopPropagation()}
            onPointerDown={startDrag}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onLoad={(event) => {
              const size = {
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              };
              setNaturalSize(size);
              fitToViewport(size);
            }}
            className={`max-w-none shrink-0 select-none rounded-lg bg-white object-contain shadow-2xl ${isDragging ? "cursor-grabbing" : canPan ? "cursor-grab" : "cursor-default"}`}
            style={naturalSize ? {
              width: `${naturalSize.width * zoom / 100}px`,
              transform: `translate(${pan.x}px, ${pan.y}px)`,
            } : undefined}
          />
        </div>
      </div>

      {images.length > 1 && (
        <>
          <button
            type="button"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={previousImage}
            className="absolute left-3 top-1/2 z-20 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/15 bg-black/70 text-white shadow-xl transition hover:bg-black focus-ring sm:left-5"
            aria-label={t("image.previous")}
          >
            <ChevronLeft className="h-7 w-7" />
          </button>
          <button
            type="button"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={nextImage}
            className="absolute right-3 top-1/2 z-20 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/15 bg-black/70 text-white shadow-xl transition hover:bg-black focus-ring sm:right-5"
            aria-label={t("image.next")}
          >
            <ChevronRight className="h-7 w-7" />
          </button>
          <span className="pointer-events-none absolute bottom-3 left-1/2 z-20 -translate-x-1/2 rounded-full bg-black/75 px-3 py-1 font-mono text-xs text-white">
            {activeIndex + 1} / {images.length}
          </span>
        </>
      )}
    </div>
  );
}
