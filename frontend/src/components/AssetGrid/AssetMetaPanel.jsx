import React from 'react';
import { Badge } from '../ui';
import {
  META_SECTIONS,
  FIELD_KIND,
  EVENT_FIELD_LABELS,
  fieldLabel,
  formatFieldValue,
  formatDuration,
  tagText,
  hasValue,
} from './assetMeta';

/**
 * AssetMetaPanel：Phase 1 完整感知 metadata 的分區呈現。
 *
 * 以 assetMeta.js 的 META_SECTIONS 資料驅動渲染：逐區挑出「有值」的欄位，依其 kind 選 renderer。
 * 三種 metadata（Image / Video / ComplexVideo）以欄位存在與否自然適應——某區全無值即整區隱藏，
 * 故複雜影片不會出現品質分 / 主體框等不存在的欄位。
 */

// caption / 電影評論等長文：標籤在上、整段內容在下（避免左右對齊擠壓長句）
const LONG_TEXT_KEYS = new Set(['caption', 'cinematic_critique']);
// 事件索引中代表「秒數」的欄位，統一格式化為 mm:ss
const EVENT_TIME_KEYS = new Set(['start_time', 'end_time', 'key_timestamp']);

/** 把 SubjectBbox 物件格式化成「(x1, y1) → (x2, y2)」（座標四捨五入為整數百分比）。 */
function formatBboxCoords(box) {
  const round = (n) => Math.round(Number(n) || 0);
  return `(${round(box.x1)}, ${round(box.y1)}) → (${round(box.x2)}, ${round(box.y2)})`;
}

/** 一般欄位列：左標籤、右值（左右對齊，長值換行）。 */
function InfoRow({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-xs text-ink-faint shrink-0">{label}</span>
      <span className="text-sm text-ink text-right break-words">{children}</span>
    </div>
  );
}

/** 長文欄位：標籤在上、整段內容在下。 */
function TextBlock({ label, text }) {
  return (
    <div className="py-1.5">
      <p className="text-xs text-ink-faint mb-1">{label}</p>
      <p className="text-sm text-ink leading-relaxed whitespace-pre-wrap">{text}</p>
    </div>
  );
}

/** 標籤列：字串陣列 → Badge 串（環境音等可能為物件，以 tagText 正規化）。 */
function TagRow({ label, items }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-xs text-ink-faint shrink-0">{label}</span>
      <div className="flex flex-wrap gap-1 justify-end">
        {items.map((item, idx) => (
          <Badge key={idx} tone="neutral">{tagText(item)}</Badge>
        ))}
      </div>
    </div>
  );
}

/** 主色調列：每色一個色塊 swatch + 色碼（色塊用資料值上色，非主題色，故用 inline style）。 */
function ColorRow({ label, colors }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-xs text-ink-faint shrink-0">{label}</span>
      <div className="flex flex-wrap gap-2 justify-end">
        {colors.map((color, idx) => (
          <span key={idx} className="flex items-center gap-1 text-[11px] text-ink-muted">
            <span className="w-4 h-4 rounded border border-border" style={{ backgroundColor: color }} />
            {color}
          </span>
        ))}
      </div>
    </div>
  );
}

/** 主體保留框座標列（框本身已疊在媒體區，此處列數值）。 */
function BboxRow({ value }) {
  return <InfoRow label={fieldLabel('subject_bbox')}>{`${formatBboxCoords(value)} %`}</InfoRow>;
}

/** 臉部資訊：偵測到臉部 / 數量 / 最大臉部佔比，逐項成列。 */
function FacesRows({ value }) {
  return (
    <>
      <InfoRow label={fieldLabel('has_faces')}>{formatFieldValue('has_faces', value.has_faces)}</InfoRow>
      {hasValue(value.face_count) && (
        <InfoRow label={fieldLabel('face_count')}>{value.face_count}</InfoRow>
      )}
      {hasValue(value.largest_face_ratio) && (
        <InfoRow label={fieldLabel('largest_face_ratio')}>
          {formatFieldValue('largest_face_ratio', value.largest_face_ratio)}
        </InfoRow>
      )}
    </>
  );
}

/** 語音逐字稿：全文 + 可摺疊分段（每段含起訖時間）。 */
function TranscriptBlock({ value }) {
  const segments = Array.isArray(value.segments) ? value.segments : [];
  return (
    <div className="py-1.5">
      <p className="text-xs text-ink-faint mb-1">{fieldLabel('audio_transcript')}</p>
      {hasValue(value.text) && (
        <p className="text-sm text-ink leading-relaxed whitespace-pre-wrap">{value.text}</p>
      )}
      {segments.length > 0 && (
        <details className="mt-2">
          <summary className="text-xs text-ink-faint cursor-pointer hover:text-ink">分段（{segments.length}）</summary>
          <div className="mt-1.5 flex flex-col gap-1">
            {segments.map((seg, idx) => (
              <div key={idx} className="flex gap-2 text-xs text-ink-muted">
                <span className="shrink-0 text-ink-faint">{formatDuration(seg.start)}–{formatDuration(seg.end)}</span>
                <span className="break-words">{seg.text}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

/** 場景切點：秒數陣列 → 一串時間點 Badge。 */
function SceneCutsBlock({ value }) {
  return (
    <div className="py-1.5">
      <p className="text-xs text-ink-faint mb-1.5">{fieldLabel('scene_cuts')}（{value.length}）</p>
      <div className="flex flex-wrap gap-1">
        {value.map((sec, idx) => (
          <Badge key={idx} tone="info">{formatDuration(sec)}</Badge>
        ))}
      </div>
    </div>
  );
}

/** 把事件子欄位值格式化（時間 → mm:ss、bbox → 座標、陣列 → 頓號連接）。 */
function renderEventValue(key, value) {
  if (EVENT_TIME_KEYS.has(key)) return formatDuration(value);
  if (key === 'subject_bbox' && value && typeof value === 'object') return formatBboxCoords(value);
  if (Array.isArray(value)) return value.map(tagText).join('、');
  return String(value);
}

/** 單一多模態事件卡：動態列出事件的各子欄位（schema 不固定，未知 key 退回原 key）。 */
function EventCard({ event, index }) {
  return (
    <div className="bg-elevated border border-border rounded-lg p-3">
      <p className="text-xs font-semibold text-ink-muted mb-1.5">事件 #{index + 1}</p>
      <div className="flex flex-col gap-1">
        {Object.entries(event).map(([key, value]) => {
          if (!hasValue(value)) return null;
          return (
            <div key={key} className="flex items-start justify-between gap-4">
              <span className="text-xs text-ink-faint shrink-0">{EVENT_FIELD_LABELS[key] || key}</span>
              <span className="text-sm text-ink text-right break-words">{renderEventValue(key, value)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 多模態事件索引：逐段事件卡（複雜影片特有）。 */
function EventsBlock({ value }) {
  return (
    <div className="py-1.5 flex flex-col gap-2">
      {value.map((event, idx) => (
        <EventCard key={idx} event={event} index={idx} />
      ))}
    </div>
  );
}

/** 依欄位 kind 選對應 renderer 呈現單一欄位。 */
function MetaField({ fieldKey, kind, value }) {
  switch (kind) {
    case FIELD_KIND.TAGS:
      return <TagRow label={fieldLabel(fieldKey)} items={value} />;
    case FIELD_KIND.COLORS:
      return <ColorRow label={fieldLabel(fieldKey)} colors={value} />;
    case FIELD_KIND.BBOX:
      return <BboxRow value={value} />;
    case FIELD_KIND.FACES:
      return <FacesRows value={value} />;
    case FIELD_KIND.TRANSCRIPT:
      return <TranscriptBlock value={value} />;
    case FIELD_KIND.SCENE_CUTS:
      return <SceneCutsBlock value={value} />;
    case FIELD_KIND.EVENTS:
      return <EventsBlock value={value} />;
    case FIELD_KIND.TEXT:
    default:
      return LONG_TEXT_KEYS.has(fieldKey)
        ? <TextBlock label={fieldLabel(fieldKey)} text={formatFieldValue(fieldKey, value)} />
        : <InfoRow label={fieldLabel(fieldKey)}>{formatFieldValue(fieldKey, value)}</InfoRow>;
  }
}

/**
 * @param {object} metadata phase1_assets_metadata.json 該檔的 metadata 區塊（success 素材才有）
 */
export default function AssetMetaPanel({ metadata }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-start">
      {META_SECTIONS.map((section) => {
        // 只挑該區「有值」的欄位;全無值即整區隱藏(自然適應圖片/一般影片/複雜影片)
        const visibleFields = section.fields.filter((field) => hasValue(metadata[field.key]));
        if (visibleFields.length === 0) return null;
        return (
          <section key={section.id} className="bg-surface border border-border rounded-xl p-4">
            <h3 className="text-sm font-semibold text-ink mb-2">{section.title}</h3>
            <div className="divide-y divide-border/40">
              {visibleFields.map((field) => (
                <MetaField key={field.key} fieldKey={field.key} kind={field.kind} value={metadata[field.key]} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
