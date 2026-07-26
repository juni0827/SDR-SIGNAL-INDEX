import { create } from "zustand";

interface UIState {
  sidebar: boolean;
  command: boolean;
  setSidebar(value: boolean): void;
  setCommand(value: boolean): void;
}
export const useUI = create<UIState>((set) => ({
  sidebar: false,
  command: false,
  setSidebar: (sidebar) => set({sidebar}),
  setCommand: (command) => set({command}),
}));

