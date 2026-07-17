// src/lib/types.ts — shared frontend-only types (not persisted)

import type { QueryResult, SheetInfo } from "@/lib/api";

export interface Session {
  id: string;
  dbId?: number;
  title: string;
  createdAt: string;
  messages: Message[];
}

export interface MessageErrorInfo {
  message:    string;   // raw DB/API error message
  error_type: string;   // e.g. "SQL_EXECUTION", "VALIDATION", "NETWORK"
  root_cause: string;   // human-readable explanation
  sql_query?: string;   // failed SQL (if any)
  question?:  string;   // original user question, used for Retry
}

export interface Message {
  id:        string;
  role:      "user" | "assistant";
  content:   string;
  result?:   QueryResult;
  loading?:  boolean;
  errorInfo?: MessageErrorInfo;
}

export interface AttachedFile {
  id: number;
  name: string;
  type: string;
  category: "structured" | "document" | "image_ocr" | "unknown"; // controls how response is rendered
  rowCount: number;
  colCount: number;
  columns: string[];
  sheetName: string | null;
}

export interface SheetPickerData {
  fileName: string;
  sheets: SheetInfo[];
}

export type SheetPickerQueue = SheetPickerData[];
