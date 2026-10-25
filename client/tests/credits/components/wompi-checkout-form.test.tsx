import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WompiCheckoutForm } from "@/credits/components/wompi-checkout/wompi-checkout-form";
import type { PaymentSummary } from "@/credits/types/credit-types";

const navigateMock = vi.fn();
vi.mock("react-router", () => ({
  useNavigate: () => navigateMock,
}));

const successMock = vi.fn();
vi.mock("@/context/toast-context", () => ({
  useToast: () => ({
    error: vi.fn(),
    success: successMock,
    info: vi.fn(),
    warning: vi.fn(),
    toasts: [],
    dismiss: vi.fn(),
  }),
}));

const payment: PaymentSummary = {
  id: "pay-1",
  limitPayDate: "2026-11-01",
  paymentDate: null,
  paymentAmount: 150000,
  installmentNumber: 3,
  principalPayment: 120000,
  totalInterestAmount: 30000,
  otherCharges: 0,
  status: "PENDIENTE",
};

const makeResponse = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: vi.fn().mockResolvedValue(body),
  }) as unknown as Response;

describe("WompiCheckoutForm", () => {
  beforeEach(() => {
    navigateMock.mockClear();
    successMock.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("pays with Nequi, polls while PENDING, and calls onDone once APPROVED", { timeout: 10000 }, async () => {
    const attempt = { id: "att-1", status: "PENDING", providerReference: "ref", providerTransactionId: "txn-1", chargeMode: "CHECKOUT" };
    const fetchMock = vi.fn((url: string) => {
      // Ojo: "/transactions/" (polling) contiene "/transaction" (creación) como
      // substring -- hay que chequear el patrón más específico primero.
      if (String(url).includes("/transactions/")) {
        return Promise.resolve(makeResponse(200, { ...attempt, status: "APPROVED" }));
      }
      if (String(url).includes("/transaction")) {
        return Promise.resolve(
          makeResponse(201, { attempt, threeDsChallenge: null, redirectAction: null }),
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const onDone = vi.fn();
    const onCancel = vi.fn();
    render(<WompiCheckoutForm payment={payment} currencyCode="COP" onDone={onDone} onCancel={onCancel} />);

    fireEvent.change(screen.getByLabelText("Método de pago"), { target: { value: "NEQUI" } });
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: "deudor@example.com" } });
    fireEvent.change(screen.getByLabelText("Número de celular Nequi"), { target: { value: "3001234567" } });
    fireEvent.change(screen.getByLabelText("Nombre completo"), { target: { value: "Juan Perez" } });
    fireEvent.change(screen.getByLabelText("Número de documento"), { target: { value: "123456789" } });
    fireEvent.change(screen.getByLabelText("Dirección"), { target: { value: "Calle 1 # 2-3" } });
    fireEvent.change(screen.getByLabelText("Ciudad"), { target: { value: "Bogota" } });

    fireEvent.click(screen.getByRole("button", { name: "Pagar" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/credits/payments/pay-1/transaction"),
        expect.objectContaining({ method: "POST" }),
      );
    });

    await waitFor(
      () => {
        expect(onDone).toHaveBeenCalledTimes(1);
      },
      { timeout: 8000 },
    );
    expect(successMock).toHaveBeenCalled();
  });

  it("pays with Daviplata: asks for the OTP and confirms it", { timeout: 10000 }, async () => {
    const attempt = { id: "att-2", status: "PENDING", providerReference: "ref", providerTransactionId: "30612544", chargeMode: "CHECKOUT" };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (String(url).includes("/daviplata/confirm-otp")) {
        expect(JSON.parse(String(init?.body))).toEqual({ otp: "123456" });
        return Promise.resolve(makeResponse(200, { ...attempt, status: "APPROVED" }));
      }
      if (String(url).includes("/transaction")) {
        const body = JSON.parse(String(init?.body));
        expect(body).toMatchObject({ paymentMethodType: "DAVIPLATA", fullName: "Ana Perez", city: "Bogota" });
        expect(body.deviceInfo.deviceSessionId).toBeTruthy();
        return Promise.resolve(
          makeResponse(201, { attempt, threeDsChallenge: null, redirectAction: null, otpRequired: true }),
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const onDone = vi.fn();
    render(<WompiCheckoutForm payment={payment} currencyCode="COP" onDone={onDone} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Método de pago"), { target: { value: "DAVIPLATA" } });
    fireEvent.change(await screen.findByLabelText("Correo electrónico"), { target: { value: "deudor@example.com" } });
    fireEvent.change(screen.getByLabelText("Nombre completo"), { target: { value: "Ana Perez" } });
    fireEvent.change(screen.getByLabelText("Número de documento"), { target: { value: "123456789" } });
    fireEvent.change(screen.getByLabelText("Dirección"), { target: { value: "Calle 1 # 2-3" } });
    fireEvent.change(screen.getByLabelText("Ciudad"), { target: { value: "Bogota" } });
    fireEvent.click(screen.getByRole("button", { name: "Pagar" }));

    fireEvent.change(await screen.findByLabelText("Código OTP"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar pago" }));

    await waitFor(() => {
      expect(onDone).toHaveBeenCalledTimes(1);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/credits/payments/pay-1/transactions/att-2/daviplata/confirm-otp"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
