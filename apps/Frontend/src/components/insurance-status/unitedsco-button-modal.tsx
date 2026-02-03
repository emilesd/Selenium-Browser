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
interface UnitedSCOOtpModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (otp: string) => Promise<void> | void;
  isSubmitting: boolean;
}

function UnitedSCOOtpModal({
  open,
  onClose,
  onSubmit,
  isSubmitting,
}: UnitedSCOOtpModalProps) {
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
          We need the one-time password (OTP) sent by the United SCO portal
          to complete this eligibility check.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="unitedsco-otp">OTP</Label>
            <Input
              id="unitedsco-otp"
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

// ---------- Main United SCO Eligibility button component ----------
interface UnitedSCOEligibilityButtonProps {
  memberId: string;
  dateOfBirth: Date | null;
  firstName?: string;
  lastName?: string;
  isFormIncomplete: boolean;
  /** Called when backend has finished and PDF is ready */
  onPdfReady: (pdfId: number, fallbackFilename: string | null) => void;
}

export function UnitedSCOEligibilityButton({
  memberId,
  dateOfBirth,
  firstName,
  lastName,
  isFormIncomplete,
  onPdfReady,
}: UnitedSCOEligibilityButtonProps) {
  const { toast } = useToast();
  const dispatch = useAppDispatch();

  const socketRef = useRef<Socket | null>(null);
  const connectingRef = useRef<Promise<void> | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [otpModalOpen, setOtpModalOpen] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isSubmittingOtp, setIsSubmittingOtp] = useState(false);

  // Clean up socket on unmount
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

  // Lazy socket setup: called only when we actually need it (first click)
  const ensureSocketConnected = async () => {
    // If already connected, nothing to do
    if (socketRef.current && socketRef.current.connected) {
      return;
    }

    // If a connection is in progress, reuse that promise
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

      // connection error when first connecting (or later)
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
        // do not reject here because socket.io will attempt reconnection
      });

      // socket.io will emit 'reconnect_attempt' for retries
      socket.on("reconnect_attempt", (attempt: number) => {
        dispatch(
          setTaskStatus({
            status: "pending",
            message: `Realtime reconnect attempt #${attempt}`,
          })
        );
      });

      // when reconnection failed after configured attempts
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
        // terminal failure — cleanup and reject so caller can stop start flow
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
            "Connection to the server was lost. If a United SCO job was running it may have failed.",
          variant: "destructive",
        });
        // clear sessionId/OTP modal
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
            message: "OTP required for United SCO eligibility. Please enter the OTP.",
          })
        );
      });

      // OTP submitted (optional UX)
      socket.on("selenium:otp_submitted", (payload: any) => {
        if (!payload?.session_id) return;
        dispatch(
          setTaskStatus({
            status: "pending",
            message: "OTP submitted. Finishing United SCO eligibility check...",
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
                "United SCO eligibility updated and PDF attached to patient documents.",
            })
          );
          toast({
            title: "United SCO eligibility complete",
            description:
              "Patient status was updated and the eligibility PDF was saved.",
            variant: "default",
          });

          const pdfId = final?.pdfFileId;
          if (pdfId) {
            const filename =
              final?.pdfFilename ?? `eligibility_unitedsco_${memberId}.pdf`;
            onPdfReady(Number(pdfId), filename);
          }

          setSessionId(null);
          setOtpModalOpen(false);
        } else if (status === "error") {
          const msg =
            payload?.message ||
            final?.error ||
            "United SCO eligibility session failed.";
          dispatch(
            setTaskStatus({
              status: "error",
              message: msg,
            })
          );
          toast({
            title: "United SCO selenium error",
            description: msg,
            variant: "destructive",
          });

          // Ensure socket is torn down for this session (stop receiving stale events)
          try {
            closeSocket();
          } catch (e) {}
          setSessionId(null);
          setOtpModalOpen(false);
        }

        queryClient.invalidateQueries({ queryKey: QK_PATIENTS_BASE });
      });

      // explicit session error event (helpful)
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

        // tear down socket to avoid stale updates
        try {
          closeSocket();
        } catch (e) {}
        setSessionId(null);
        setOtpModalOpen(false);
      });

      // If socket.io initial connection fails permanently (very rare: client-level)
      // set a longer timeout to reject the first attempt to connect.
      const initialConnectTimeout = setTimeout(() => {
        if (!socket.connected) {
          // if still not connected after 8s, treat as failure and reject so caller can handle it
          closeSocket();
          reject(new Error("Realtime initial connection timeout"));
        }
      }, 8000);

      // When the connect resolves we should clear this timer
      socket.once("connect", () => {
        clearTimeout(initialConnectTimeout);
      });
    });

    // store promise to prevent multiple concurrent connections
    connectingRef.current = promise;

    try {
      await promise;
    } finally {
      connectingRef.current = null;
    }
  };

  const startUnitedSCOEligibility = async () => {
    if (!memberId || !dateOfBirth) {
      toast({
        title: "Missing fields",
        description: "Member ID and Date of Birth are required.",
        variant: "destructive",
      });
      return;
    }

    const formattedDob = dateOfBirth ? formatLocalDate(dateOfBirth) : "";

    const payload = {
      memberId,
      dateOfBirth: formattedDob,
      firstName,
      lastName,
      insuranceSiteKey: "UNITEDSCO", // for backend credential lookup (uses DENTAQUEST)
    };

    try {
      setIsStarting(true);

      // 1) Ensure socket is connected (lazy)
      dispatch(
        setTaskStatus({
          status: "pending",
          message: "Opening realtime channel for United SCO eligibility...",
        })
      );
      await ensureSocketConnected();

      const socket = socketRef.current;
      if (!socket || !socket.connected) {
        throw new Error("Socket connection failed");
      }

      const socketId = socket.id;

      // 2) Start the selenium job via backend
      dispatch(
        setTaskStatus({
          status: "pending",
          message: "Starting United SCO eligibility check via selenium...",
        })
      );

      const response = await apiRequest(
        "POST",
        "/api/insurance-status-unitedsco/unitedsco-eligibility",
        {
          data: JSON.stringify(payload),
          socketId,
        }
      );

      // If apiRequest threw, we would have caught above; but just in case it returns.
      let result: any = null;
      let backendError: string | null = null;

      try {
        // attempt JSON first
        result = await response.clone().json();
        backendError =
          result?.error || result?.message || result?.detail || null;
      } catch {
        // fallback to text response
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
            `United SCO selenium start failed (status ${response.status})`
        );
      }

      // Normal success path: optional: if backend returns non-error shape still check for result.error
      if (result?.error) {
        throw new Error(result.error);
      }

      if (result.status === "started" && result.session_id) {
        setSessionId(result.session_id as string);
        dispatch(
          setTaskStatus({
            status: "pending",
            message:
              "United SCO eligibility job started. Waiting for OTP or final result...",
          })
        );
      } else {
        // fallback if backend returns immediate result
        dispatch(
          setTaskStatus({
            status: "success",
            message: "United SCO eligibility completed.",
          })
        );
      }
    } catch (err: any) {
      console.error("startUnitedSCOEligibility error:", err);
      dispatch(
        setTaskStatus({
          status: "error",
          message: err?.message || "Failed to start United SCO eligibility",
        })
      );
      toast({
        title: "United SCO selenium error",
        description: err?.message || "Failed to start United SCO eligibility",
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
          "Could not submit OTP because the United SCO session or socket is not ready.",
        variant: "destructive",
      });
      return;
    }

    try {
      setIsSubmittingOtp(true);
      const resp = await apiRequest(
        "POST",
        "/api/insurance-status-unitedsco/selenium/submit-otp",
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

      // from here we rely on websocket events (otp_submitted + session_update)
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
        disabled={isFormIncomplete || isStarting}
        onClick={startUnitedSCOEligibility}
      >
        {isStarting ? (
          <>
            <LoaderCircleIcon className="h-4 w-4 mr-2 animate-spin" />
            Processing...
          </>
        ) : (
          <>
            <CheckCircle className="h-4 w-4 mr-2" />
            United SCO
          </>
        )}
      </Button>

      <UnitedSCOOtpModal
        open={otpModalOpen}
        onClose={() => setOtpModalOpen(false)}
        onSubmit={handleSubmitOtp}
        isSubmitting={isSubmittingOtp}
      />
    </>
  );
}
