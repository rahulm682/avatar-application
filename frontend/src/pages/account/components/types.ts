export type Message = {
  kind: "success" | "error";
  text: string;
} | null;