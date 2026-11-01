export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  className?: string;
  children: React.ReactNode;
  showCloseButton?: boolean;
  isFullscreen?: boolean;
  /** Nombre accesible del diálogo (WCAG 4.1.2), leído por lectores de pantalla al abrir. */
  ariaLabel?: string;
}
