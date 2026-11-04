import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ModuleBase } from "@/ui/components/common/module-base";
import { Card, CardTitle } from "@/ui/components/card";
import { Input } from "@/ui/components/inputs/input";
import { Select } from "@/ui/components/inputs/select";
import { Button } from "@/ui/components/button/button";
import { useAuth } from "@/hooks/use-auth";
import { useUser } from "@/users/hooks/use-user";
import { useUpdateUser } from "@/users/hooks/use-update-user";
import { Loader } from "@/ui/components/loader/loader";
import { DOCUMENT_TYPE_OPTIONS } from "../constants/document-type-options";

export const ProfileEditPage: React.FC = () => {
  const navigate = useNavigate();
  const { getSession } = useAuth();
  const userId = String(getSession()?.userId ?? "");
  const { user, loading } = useUser(userId);
  const { updateUser, loading: saving, error } = useUpdateUser();

  const [form, setForm] = useState({
    firstname: "",
    lastname: "",
    email: "",
    phoneNumber: "",
    documentType: "",
    documentNumber: "",
  });
  const [currentPassword, setCurrentPassword] = useState("");
  const emailChanged = !!user && form.email !== user.email;

  useEffect(() => {
    if (user) {
      setForm({
        firstname: user.firstname,
        lastname: user.lastname,
        email: user.email,
        phoneNumber: user.phoneNumber ?? "",
        documentType: user.documentType ?? "",
        documentNumber: user.documentNumber ?? "",
      });
    }
  }, [user]);

  const handleField = (field: string, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    const result = await updateUser(user.id, {
      firstname: form.firstname || undefined,
      lastname: form.lastname || undefined,
      email: form.email || undefined,
      phoneNumber: form.phoneNumber || undefined,
      documentType: form.documentType || undefined,
      documentNumber: form.documentNumber !== (user.documentNumber ?? "") ? form.documentNumber : undefined,
      currentPassword: emailChanged ? currentPassword : undefined,
    });
    if (result) navigate("/profile");
  };

  if (loading) {
    return (
      <ModuleBase pageTitle="Editar perfil" breadcrumbItems={[{ label: "Perfil", path: "/profile" }]}>
        <div className="flex h-48 items-center justify-center"><Loader loaderText="Cargando perfil..." /></div>
      </ModuleBase>
    );
  }

  return (
    <ModuleBase
      pageTitle="Editar perfil"
      breadcrumbItems={[{ label: "Perfil", path: "/profile" }]}
    >
      <form onSubmit={handleSubmit}>
        <Card>
          <CardTitle>Información personal</CardTitle>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <Input
              label="Nombre"
              id="firstname"
              value={form.firstname}
              onChange={(e) => handleField("firstname", e.target.value)}
              placeholder="Nombre"
            />
            <Input
              label="Apellido"
              id="lastname"
              value={form.lastname}
              onChange={(e) => handleField("lastname", e.target.value)}
              placeholder="Apellido"
            />
            <Input
              label="Email"
              id="email"
              type="email"
              value={form.email}
              onChange={(e) => handleField("email", e.target.value)}
              placeholder="correo@ejemplo.com"
            />
            {emailChanged && (
              <Input
                label="Contraseña actual (para cambiar el correo)"
                id="currentPassword"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Tu contraseña actual"
                autoComplete="current-password"
              />
            )}
            <Input
              label="Teléfono"
              id="phoneNumber"
              value={form.phoneNumber}
              onChange={(e) => handleField("phoneNumber", e.target.value)}
              placeholder="+57 300 000 0000"
              autoComplete="tel"
            />
            <div>
              {/* Select no expone `id`, por lo que no puede enlazarse vía htmlFor
                  sin modificar ui/components/inputs/select.tsx (fuera de alcance). */}
              <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-400">
                Tipo documento
              </label>
              <Select
                options={DOCUMENT_TYPE_OPTIONS}
                value={form.documentType}
                placeholder="Seleccionar tipo"
                onChange={(v) => handleField("documentType", v)}
              />
            </div>
            <Input
              label="N° documento"
              id="documentNumber"
              value={form.documentNumber}
              onChange={(e) => handleField("documentNumber", e.target.value)}
              placeholder="Número de documento"
            />
          </div>
        </Card>

        {error && <p className="mt-4 text-sm text-error-500">{error}</p>}

        <div className="flex items-center justify-end gap-3 mt-5">
          <Button type="button" size="sm" variant="outline" onClick={() => navigate("/profile")}>
            Cancelar
          </Button>
          <Button type="submit" size="sm" loading={saving} loadingText="Guardando...">
            Guardar cambios
          </Button>
        </div>
      </form>
    </ModuleBase>
  );
};
