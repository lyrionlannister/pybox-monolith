import type { ReactNode } from "react";

export interface ButtonProps {
  children: React.ReactNode;
  size?: "sm" | "md";
  variant?: "primary" | "outline";
  startIcon?: ReactNode;
  endIcon?: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  loading?: boolean;
  loadingText?: string;
  type?: "button" | "submit";
}
