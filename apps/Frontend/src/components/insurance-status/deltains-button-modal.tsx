import { useEffect, useRef, useState } from "react";
import { io as ioClient, Socket } from "socket.io-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CheckCircle, LoaderCircleIcon, X } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { useAppDispatch } from "@/redux/hooks";
import { setTaskStatus } from "@/redux/slices/seleniumEligibilityCheckTaskSlice";
import { formatLocalDate } from "@/utils/dateUtils";
import { QK_PATIENTS_BASE } from "@/components/patients/patient-table";

const SOCKET_URL =
  import.meta.env.VITE_API_BASE_URL_BACKEND ||
  (typeof window !== "undefined" ? window.location.origin : "");

// ---------- OTP Modal component ----------
interface DeltaInsOtpModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (otp: string) => Promise<void> | void;
  isSubmitting: boolean;
}

function DeltaInsOtpModal({
  open,
  onClose,
  onSubmit,
  isSubmitting,
}: DeltaInsOtpModalProps) {
  const [otp, setOtp] = useState("");

  useEffect(() => {
    if (!open) setOtp("");
  }, [open]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!otp.trim()) return;
    await onSubmit(otp.trim());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-slate-900 rounded-xl shadow-lg w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Enter OTP</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-500 hover:text-slate-800"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-slate-500 mb-4">
          We need the one-time password (OTP) sent to your email by Delta Dental
          Ins to complete this eligibility check.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="deltains-otp">OTP</Label>
            <Input
              id="deltains-otp"
              placeholder="Enter OTP code"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              autoFocus
            />
          </div>
          <div className="flex justify-end gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || !otp.trim()}>
              {isSubmitting ? (
                <>
                  <LoaderCircleIcon className="w-4 h-4 mr-2 animate-spin" />
                  Submitting...
                </>
              ) : (
                "Submit OTP"
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------- Main DeltaIns Eligibility button component ----------
interface DeltaInsEligibilityButtonProps {
  memberId: string;
  dateOfBirth: Date | null;
  firstName?: string;
  lastName?: string;
  isFormIncomplete: boolean;
  onPdfReady: (pdfId: number, fallbackFilename: string | null) => void;
}

export function DeltaInsEligibilityButton({
  memberId,
  dateOfBirth,
  firstName,
  lastName,
  isFormIncomplete,
  onPdfReady,
}: DeltaInsEligibilityButtonProps) {
  const { toast } = useToast();
  const dispatch = useAppDispatch();

  const isDeltaInsFormIncomplete =
    !dateOfBirth || (!memberId && !firstName && !lastName);

  const socketRef = useRef<Socket | null>(null);
  const connectingRef = useRef<Promise<void> | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [otpModalOpen, setOtpModalOpen] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isSubmittingOtp, setIsSubmittingOtp] = useState(false);

  useEffect(() => {
    return () => {
      if (socketRef.current) {
        socketRef.current.removeAllListeners();
        socketRef.current.disconnect();
        socketRef.current = null;
      }
      connectingRef.current = null;
    };
  }, []);

  const closeSocket = () => {
    try {
      socketRef.current?.removeAllListeners();
      socketRef.current?.disconnect();
    } catch (e) {
      // ignore
    } finally {
      socketRef.current = null;
    }
  };

  const ensureSocketConnected = async () => {
    if (socketRef.current && socketRef.current.connected) {
      return;
    }

    if (connectingRef.current) {
      return connectingRef.current;
    }

    const promise = new Promise<void>((resolve, reject) => {
      const socket = ioClient(SOCKET_URL, {
        withCredentials: true,
      });

      socketRef.current = socket;

      socket.on("connect", () => {
        resolve();
      });

      socket.on("connect_error", (err: any) => {
        dispatch(
          setTaskStatus({
            status: "error",
            message: "Connection failed",
          })
        );
        toast({
          title: "Realtime connection failed",
          description:
            "Could not connect to realtime server. Retrying automatically...",
          variant: "destructive",
        });
      });

      socket.on("reconnect_attempt", (attempt: number) => {
        dispatch(
          setTaskStatus({
            status: "pending",
            message: `Realtime reconnect attempt #${attempt}`,
          })
        );
      });

      socket.on("reconnect_failed", () => {
        dispatch(
          setTaskStatus({
            status: "error",
            message: "Reconnect failed",
          })
        );
        toast({
          title: "Realtime reconnect failed",
          description:
            "Connection to realtime server could not be re-established. Please try again later.",
          variant: "destructive",
        });
        closeSocket();
        reject(new Error("Realtime reconnect failed"));
      });

      socket.on("disconnect", (reason: any) => {
        dispatch(
          setTaskStatus({
            status: "error",
            message: "Connection disconnected",
          })
        );
        toast({
          title: "Connection Disconnected",
          description:
            "Connection to the server was lost. If a DeltaIns job was running it may have failed.",
          variant: "destructive",
        });
        setSessionId(null);
        setOtpModalOpen(false);
      });

      // OTP required
      socket.on("selenium:otp_required", (payload: any) => {
        if (!payload?.session_id) return;
        setSessionId(payload.session_id);
        setOtpModalOpen(true);
        dispatch(
          setTaskStatus({
            status: "pending",
            message: "OTP required for Delta Dental Ins eligibility. Please enter the code sent to your email.",
          })
        );
      });

      // OTP submitted
      socket.on("selenium:otp_submitted", (payload: any) => {
        if (!payload?.session_id) return;
        dispatch(
          setTaskStatus({
            status: "pending",
            message: "OTP submitted. Finishing Delta Dental Ins eligibility check...",
          })
        );
      });

      // Session update
      socket.on("selenium:session_update", (payload: any) => {
        const { session_id, status, final } = payload || {};
        if (!session_id) return;

        if (status === "completed") {
          dispatch(
            setTaskStatus({
              status: "success",
              message:
                "Delta Dental Ins eligibility updated and PDF attached to patient documents.",
            })
          );
          toast({
            title: "Delta Dental Ins eligibility complete",
            description:
              "Patient status was updated and the eligibility PDF was saved.",
            variant: "default",
          });

          const pdfId = final?.pdfFileId;
          if (pdfId) {
            const filename =
              final?.pdfFilename ?? `eligibility_deltains_${memberId}.pdf`;
            onPdfReady(Number(pdfId), filename);
          }

          setSessionId(null);
          setOtpModalOpen(false);
        } else if (status === "error") {
          const msg =
            payload?.message ||
            final?.error ||
            "Delta Dental Ins eligibility session failed.";
          dispatch(
            setTaskStatus({
              status: "error",
              message: msg,
            })
          );
          toast({
            title: "Delta Dental Ins selenium error",
            description: msg,
            variant: "destructive",
          });

          try {
            closeSocket();
          } catch (e) {}
          setSessionId(null);
          setOtpModalOpen(false);
        }

        queryClient.invalidateQueries({ queryKey: QK_PATIENTS_BASE });
      });

      // explicit session error event
      socket.on("selenium:session_error", (payload: any) => {
        const msg = payload?.message || "Selenium session error";

        dispatch(
          setTaskStatus({
            status: "error",
            message: msg,
          })
        );

        toast({
          title: "Selenium session error",
          description: msg,
          variant: "destructive",
        });

        try {
          closeSocket();
        } catch (e) {}
        setSessionId(null);
        setOtpModalOpen(false);
      });

      const initialConnectTimeout = setTimeout(() => {
        if (!socket.connected) {
          closeSocket();
          reject(new Error("Realtime initial connection timeout"));
        }
      }, 8000);

      socket.once("connect", () => {
        clearTimeout(initialConnectTimeout);
      });
    });

    connectingRef.current = promise;

    try {
      await promise;
    } finally {
      connectingRef.current = null;
    }
  };

  const startDeltaInsEligibility = async () => {
    if (!dateOfBirth) {
      toast({
        title: "Missing fields",
        description: "Date of Birth is required for Delta Dental Ins eligibility.",
        variant: "destructive",
      });
      return;
    }

    if (!memberId && !firstName && !lastName) {
      toast({
        title: "Missing fields",
        description: "Member ID, First Name, or Last Name is required for Delta Dental Ins eligibility.",
        variant: "destructive",
      });
      return;
    }

    const formattedDob = dateOfBirth ? formatLocalDate(dateOfBirth) : "";

    const payload = {
      memberId: memberId || "",
      dateOfBirth: formattedDob,
      firstName: firstName || "",
      lastName: lastName || "",
      insuranceSiteKey: "DELTAINS",
    };

    try {
      setIsStarting(true);

      dispatch(
        setTaskStatus({
          status: "pending",
          message: "Opening realtime channel for Delta Dental Ins eligibility...",
        })
      );
      await ensureSocketConnected();

      const socket = socketRef.current;
      if (!socket || !socket.connected) {
        throw new Error("Socket connection failed");
      }

      const socketId = socket.id;

      dispatch(
        setTaskStatus({
          status: "pending",
          message: "Starting Delta Dental Ins eligibility check via selenium...",
        })
      );

      const response = await apiRequest(
        "POST",
        "/api/insurance-status-deltains/deltains-eligibility",
        {
          data: JSON.stringify(payload),
          socketId,
        }
      );

      let result: any = null;
      let backendError: string | null = null;

      try {
        result = await response.clone().json();
        backendError =
          result?.error || result?.message || result?.detail || null;
      } catch {
        try {
          const text = await response.clone().text();
          backendError = text?.trim() || null;
        } catch {
          backendError = null;
        }
      }

      if (!response.ok) {
        throw new Error(
          backendError ||
            `Delta Dental Ins selenium start failed (status ${response.status})`
        );
      }

      if (result?.error) {
        throw new Error(result.error);
      }

      if (result.status === "started" && result.session_id) {
        setSessionId(result.session_id as string);
        dispatch(
          setTaskStatus({
            status: "pending",
            message:
              "Delta Dental Ins eligibility job started. Waiting for OTP or final result...",
          })
        );
      } else {
        dispatch(
          setTaskStatus({
            status: "success",
            message: "Delta Dental Ins eligibility completed.",
          })
        );
      }
    } catch (err: any) {
      console.error("startDeltaInsEligibility error:", err);
      dispatch(
        setTaskStatus({
          status: "error",
          message: err?.message || "Failed to start Delta Dental Ins eligibility",
        })
      );
      toast({
        title: "Delta Dental Ins selenium error",
        description: err?.message || "Failed to start Delta Dental Ins eligibility",
        variant: "destructive",
      });
    } finally {
      setIsStarting(false);
    }
  };

  const handleSubmitOtp = async (otp: string) => {
    if (!sessionId || !socketRef.current || !socketRef.current.connected) {
      toast({
        title: "Session not ready",
        description:
          "Could not submit OTP because the DeltaIns session or socket is not ready.",
        variant: "destructive",
      });
      return;
    }

    try {
      setIsSubmittingOtp(true);
      const resp = await apiRequest(
        "POST",
        "/api/insurance-status-deltains/selenium/submit-otp",
        {
          session_id: sessionId,
          otp,
          socketId: socketRef.current.id,
        }
      );
      const data = await resp.json();
      if (!resp.ok || data.error) {
        throw new Error(data.error || "Failed to submit OTP");
      }

      setOtpModalOpen(false);
    } catch (err: any) {
      console.error("handleSubmitOtp error:", err);
      toast({
        title: "Failed to submit OTP",
        description: err?.message || "Error forwarding OTP to selenium agent",
        variant: "destructive",
      });
    } finally {
      setIsSubmittingOtp(false);
    }
  };

  return (
    <>
      <Button
        className="w-full"
        variant="outline"
        disabled={isDeltaInsFormIncomplete || isStarting}
        onClick={startDeltaInsEligibility}
      >
        {isStarting ? (
          <>
            <LoaderCircleIcon className="h-4 w-4 mr-2 animate-spin" />
            Processing...
          </>
        ) : (
          <>
            <CheckCircle className="h-4 w-4 mr-2" />
            Delta Dental Ins
          </>
        )}
      </Button>

      <DeltaInsOtpModal
        open={otpModalOpen}
        onClose={() => setOtpModalOpen(false)}
        onSubmit={handleSubmitOtp}
        isSubmitting={isSubmittingOtp}
      />
    </>
  );
}
