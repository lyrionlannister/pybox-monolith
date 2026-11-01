import { Link } from "react-router";

import { PageMeta } from "./page-meta";
import { useGoBack } from "../../hooks/use-go-back";

export const NotFound: React.FC = () => {
  const goBack = useGoBack();
  return (
    <>
      <PageMeta
        title="Página no encontrada"
        description="Esta página no existe"
      />
      <div className="relative flex flex-col items-center justify-center min-h-screen p-6 overflow-hidden z-1">
        <div className="mx-auto w-full max-w-60.5 text-center sm:sm:max-w-118">
          <h1 className="mb-8 font-bold text-gray-800 text-title-md dark:text-white/90 xl:text-title-2xl">
            404
          </h1>
          <div className="flex gap-6 items-center justify-center">
            <Link
              to="/"
              className="inline-flex items-center justify-center rounded-lg border border-gray-300 bg-white px-5 py-3.5 text-sm font-medium text-gray-700 shadow-theme-xs hover:bg-gray-50 hover:text-gray-800 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-white/3 dark:hover:text-gray-200"
            >
              Inicio
            </Link>

            <button
              className="inline-flex items-center justify-center rounded-lg border border-gray-300 bg-white px-5 py-3.5 text-sm font-medium text-gray-700 shadow-theme-xs hover:bg-gray-50 hover:text-gray-800 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-white/3 dark:hover:text-gray-200"
              onClick={goBack}
            >
              Volver
            </button>
          </div>
        </div>
        <p className="absolute text-sm text-center text-gray-500 -translate-x-1/2 bottom-6 left-1/2 dark:text-gray-400">
          &copy; {new Date().getFullYear()}
        </p>
      </div>
    </>
  );
};
