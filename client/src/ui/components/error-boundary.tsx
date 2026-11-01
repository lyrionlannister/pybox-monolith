import { Component } from "react";
import type { ErrorBoundaryProps } from "@/types/props/error-boundary-props";

interface State {
  hasError: boolean;
}

/** Clase obligatoria: React (incluyendo v19) no expone hook equivalente a getDerivedStateFromError. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, State> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Sin esto, un error de render en producción desaparecía sin rastro: ni consola
    // ni forma de correlacionarlo con un reporte del usuario.
    console.error("[error-boundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="flex h-screen items-center justify-center text-center">
            <div>
              <p className="text-lg font-semibold text-gray-800 dark:text-white">
                Ocurrió un error inesperado
              </p>
              <button
                type="button"
                onClick={() => this.setState({ hasError: false })}
                className="mt-4 text-sm text-brand-500 hover:underline"
              >
                Reintentar
              </button>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
