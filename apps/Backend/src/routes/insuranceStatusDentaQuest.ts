import { Router, Request, Response } from "express";
import { storage } from "../storage";
import {
  forwardToSeleniumDentaQuestEligibilityAgent,
  forwardOtpToSeleniumDentaQuestAgent,
  getSeleniumDentaQuestSessionStatus,
} from "../services/seleniumDentaQuestInsuranceEligibilityClient";
import fs from "fs/promises";
import fsSync from "fs";
import path from "path";
import PDFDocument from "pdfkit";
import { emptyFolderContainingFile } from "../utils/emptyTempFolder";
import {
  InsertPatient,
  insertPatientSchema,
} from "../../../../packages/db/types/patient-types";
import { io } from "../socket";

const router = Router();

/** Job context stored in memory by sessionId */
interface DentaQuestJobContext {
  userId: number;
  insuranceEligibilityData: any; // parsed, enriched (includes username/password)
  socketId?: string;
}

const dentaquestJobs: Record<string, DentaQuestJobContext> = {};

/** Utility: naive name splitter */
function splitName(fullName?: string | null) {
  if (!fullName) return { firstName: "", lastName: "" };
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  const firstName = parts.shift() ?? "";
  const lastName = parts.join(" ") ?? "";
  return { firstName, lastName };
}

async function imageToPdfBuffer(imagePath: string): Promise<Buffer> {
  return new Promise<Buffer>((resolve, reject) => {
    try {
      const doc = new PDFDocument({ autoFirstPage: false });
      const chunks: Uint8Array[] = [];

      doc.on("data", (chunk: any) => chunks.push(chunk));
      doc.on("end", () => resolve(Buffer.concat(chunks)));
      doc.on("error", (err: any) => reject(err));

      const A4_WIDTH = 595.28; // points
      const A4_HEIGHT = 841.89; // points

      doc.addPage({ size: [A4_WIDTH, A4_HEIGHT] });

      doc.image(imagePath, 0, 0, {
        fit: [A4_WIDTH, A4_HEIGHT],
        align: "center",
        valign: "center",
      });

      doc.end();
    } catch (err) {
      reject(err);
    }
  });
}

/**
 * Ensure patient exists for given insuranceId.
 */
async function createOrUpdatePatientByInsuranceId(options: {
  insuranceId: string;
  firstName?: string | null;
  lastName?: string | null;
  dob?: string | Date | null;
  userId: number;
}) {
  const { insuranceId, firstName, lastName, dob, userId } = options;
  if (!insuranceId) throw new Error("Missing insuranceId");

  const incomingFirst = (firstName || "").trim();
  const incomingLast = (lastName || "").trim();

  let patient = await storage.getPatientByInsuranceId(insuranceId);

  if (patient && patient.id) {
    const updates: any = {};
    if (
      incomingFirst &&
      String(patient.firstName ?? "").trim() !== incomingFirst
    ) {
      updates.firstName = incomingFirst;
    }
    if (
      incomingLast &&
      String(patient.lastName ?? "").trim() !== incomingLast
    ) {
      updates.lastName = incomingLast;
    }
    if (Object.keys(updates).length > 0) {
      await storage.updatePatient(patient.id, updates);
    }
    return;
  } else {
    const createPayload: any = {
      firstName: incomingFirst,
      lastName: incomingLast,
      dateOfBirth: dob,
      gender: "",
      phone: "",
      userId,
      insuranceId,
    };
    let patientData: InsertPatient;
    try {
      patientData = insertPatientSchema.parse(createPayload);
    } catch (err) {
      const safePayload = { ...createPayload };
      delete (safePayload as any).dateOfBirth;
      patientData = insertPatientSchema.parse(safePayload);
    }
    await storage.createPatient(patientData);
  }
}

/**
 * When Selenium finishes for a given sessionId, run your patient + PDF pipeline,
 * and return the final API response shape.
 */
async function handleDentaQuestCompletedJob(
  sessionId: string,
  job: DentaQuestJobContext,
  seleniumResult: any
) {
  let createdPdfFileId: number | null = null;
  const outputResult: any = {};

  // We'll wrap the processing in try/catch/finally so cleanup always runs
  try {
    const insuranceEligibilityData = job.insuranceEligibilityData;
    
    // 1) Get Member ID - prefer the one extracted from the page by Selenium,
    // since we now allow searching by name only
    let insuranceId = String(seleniumResult?.memberId ?? "").trim();
    if (!insuranceId) {
      // Fallback to the one provided in the request
      insuranceId = String(insuranceEligibilityData.memberId ?? "").trim();
    }
    
    console.log(`[dentaquest-eligibility] Insurance ID: ${insuranceId || "(none)"}`);

    // 2) Create or update patient (with name from selenium result if available)
    const patientNameFromResult =
      typeof seleniumResult?.patientName === "string"
        ? seleniumResult.patientName.trim()
        : null;

    // Get name from request data as fallback
    let firstName = insuranceEligibilityData.firstName || "";
    let lastName = insuranceEligibilityData.lastName || "";
    
    // Override with name from Selenium result if available
    if (patientNameFromResult) {
      const parsedName = splitName(patientNameFromResult);
      firstName = parsedName.firstName || firstName;
      lastName = parsedName.lastName || lastName;
    }

    // Create or update patient if we have an insurance ID
    if (insuranceId) {
      await createOrUpdatePatientByInsuranceId({
        insuranceId,
        firstName,
        lastName,
        dob: insuranceEligibilityData.dateOfBirth,
        userId: job.userId,
      });
    } else {
      console.log("[dentaquest-eligibility] No Member ID available - will try to find patient by name/DOB");
    }

    // 3) Update patient status + PDF upload
    // First try to find by insurance ID, then by name + DOB
    let patient = insuranceId 
      ? await storage.getPatientByInsuranceId(insuranceId)
      : null;
    
    // If not found by ID and we have name + DOB, try to find by those
    if (!patient && firstName && lastName) {
      console.log(`[dentaquest-eligibility] Looking up patient by name: ${firstName} ${lastName}`);
      const patients = await storage.getPatientsByUserId(job.userId);
      patient = patients.find(p => 
        p.firstName?.toLowerCase() === firstName.toLowerCase() &&
        p.lastName?.toLowerCase() === lastName.toLowerCase()
      ) || null;
      
      // If found and we now have the insurance ID, update the patient record
      if (patient && insuranceId) {
        await storage.updatePatient(patient.id, { insuranceId });
        console.log(`[dentaquest-eligibility] Updated patient ${patient.id} with insuranceId: ${insuranceId}`);
      }
    }
    
    // Determine eligibility status from Selenium result
    const eligibilityStatus = seleniumResult.eligibility === "active" ? "ACTIVE" : "INACTIVE";
    console.log(`[dentaquest-eligibility] Eligibility status from DentaQuest: ${eligibilityStatus}`);
    
    // If still no patient found, CREATE a new one with the data we have
    if (!patient?.id && firstName && lastName) {
      console.log(`[dentaquest-eligibility] Creating new patient: ${firstName} ${lastName} with status: ${eligibilityStatus}`);
      
      const createPayload: any = {
        firstName,
        lastName,
        dateOfBirth: insuranceEligibilityData.dateOfBirth || null,
        gender: "",
        phone: "",
        userId: job.userId,
        insuranceId: insuranceId || null,
        insuranceProvider: "DentaQuest", // Set insurance provider
        status: eligibilityStatus, // Set status from eligibility check
      };
      
      try {
        const patientData = insertPatientSchema.parse(createPayload);
        const newPatient = await storage.createPatient(patientData);
        if (newPatient) {
          patient = newPatient;
          console.log(`[dentaquest-eligibility] Created new patient with ID: ${patient.id}, status: ${eligibilityStatus}`);
        }
      } catch (err: any) {
        // Try without dateOfBirth if it fails
        try {
          const safePayload = { ...createPayload };
          delete safePayload.dateOfBirth;
          const patientData = insertPatientSchema.parse(safePayload);
          const newPatient = await storage.createPatient(patientData);
          if (newPatient) {
            patient = newPatient;
            console.log(`[dentaquest-eligibility] Created new patient (no DOB) with ID: ${patient.id}, status: ${eligibilityStatus}`);
          }
        } catch (err2: any) {
          console.error(`[dentaquest-eligibility] Failed to create patient: ${err2?.message}`);
        }
      }
    }
    
    if (!patient?.id) {
      outputResult.patientUpdateStatus =
        "Patient not found and could not be created";
      return {
        patientUpdateStatus: outputResult.patientUpdateStatus,
        pdfUploadStatus: "none",
        pdfFileId: null,
      };
    }

    // Update patient status from DentaQuest eligibility result
    await storage.updatePatient(patient.id, { status: eligibilityStatus });
    outputResult.patientUpdateStatus = `Patient ${patient.id} status set to ${eligibilityStatus} (DentaQuest eligibility: ${seleniumResult.eligibility})`;
    console.log(`[dentaquest-eligibility] ${outputResult.patientUpdateStatus}`);

    // Handle PDF or convert screenshot -> pdf if available
    let pdfBuffer: Buffer | null = null;
    let generatedPdfPath: string | null = null;

    if (
      seleniumResult &&
      seleniumResult.ss_path &&
      typeof seleniumResult.ss_path === "string"
    ) {
      try {
        if (!fsSync.existsSync(seleniumResult.ss_path)) {
          throw new Error(
            `File not found: ${seleniumResult.ss_path}`
          );
        }

        // Check if the file is already a PDF (from Page.printToPDF)
        if (seleniumResult.ss_path.endsWith(".pdf")) {
          // Read PDF directly
          pdfBuffer = await fs.readFile(seleniumResult.ss_path);
          generatedPdfPath = seleniumResult.ss_path;
          seleniumResult.pdf_path = generatedPdfPath;
          console.log(`[dentaquest-eligibility] Using PDF directly from Selenium: ${generatedPdfPath}`);
        } else if (
          seleniumResult.ss_path.endsWith(".png") ||
          seleniumResult.ss_path.endsWith(".jpg") ||
          seleniumResult.ss_path.endsWith(".jpeg")
        ) {
          // Convert image to PDF
          pdfBuffer = await imageToPdfBuffer(seleniumResult.ss_path);

          const pdfFileName = `dentaquest_eligibility_${insuranceEligibilityData.memberId}_${Date.now()}.pdf`;
          generatedPdfPath = path.join(
            path.dirname(seleniumResult.ss_path),
            pdfFileName
          );
          await fs.writeFile(generatedPdfPath, pdfBuffer);
          seleniumResult.pdf_path = generatedPdfPath;
          console.log(`[dentaquest-eligibility] Converted screenshot to PDF: ${generatedPdfPath}`);
        } else {
          outputResult.pdfUploadStatus =
            `Unsupported file format: ${seleniumResult.ss_path}`;
        }
      } catch (err: any) {
        console.error("Failed to process PDF/screenshot:", err);
        outputResult.pdfUploadStatus = `Failed to process file: ${String(err)}`;
      }
    } else {
      outputResult.pdfUploadStatus =
        "No valid file path (ss_path) provided by Selenium; nothing to upload.";
    }

    if (pdfBuffer && generatedPdfPath) {
      const groupTitle = "Eligibility Status";
      const groupTitleKey = "ELIGIBILITY_STATUS";

      let group = await storage.findPdfGroupByPatientTitleKey(
        patient.id,
        groupTitleKey
      );
      if (!group) {
        group = await storage.createPdfGroup(
          patient.id,
          groupTitle,
          groupTitleKey
        );
      }
      if (!group?.id) {
        throw new Error("PDF group creation failed: missing group ID");
      }

      const created = await storage.createPdfFile(
        group.id,
        path.basename(generatedPdfPath),
        pdfBuffer
      );
      if (created && typeof created === "object" && "id" in created) {
        createdPdfFileId = Number(created.id);
      }
      outputResult.pdfUploadStatus = `PDF saved to group: ${group.title}`;
    } else {
      outputResult.pdfUploadStatus =
        "No valid PDF path provided by Selenium, Couldn't upload pdf to server.";
    }

    return {
      patientUpdateStatus: outputResult.patientUpdateStatus,
      pdfUploadStatus: outputResult.pdfUploadStatus,
      pdfFileId: createdPdfFileId,
    };
  } catch (err: any) {
    return {
      patientUpdateStatus: outputResult.patientUpdateStatus,
      pdfUploadStatus:
        outputResult.pdfUploadStatus ??
        `Failed to process DentaQuest job: ${err?.message ?? String(err)}`,
      pdfFileId: createdPdfFileId,
      error: err?.message ?? String(err),
    };
  } finally {
    // ALWAYS attempt cleanup of temp files
    try {
      if (seleniumResult && seleniumResult.pdf_path) {
        await emptyFolderContainingFile(seleniumResult.pdf_path);
      } else if (seleniumResult && seleniumResult.ss_path) {
        await emptyFolderContainingFile(seleniumResult.ss_path);
      } else {
        console.log(
          `[dentaquest-eligibility] no pdf_path or ss_path available to cleanup`
        );
      }
    } catch (cleanupErr) {
      console.error(
        `[dentaquest-eligibility cleanup failed for ${seleniumResult?.pdf_path ?? seleniumResult?.ss_path}]`,
        cleanupErr
      );
    }
  }
}

// --- top of file, alongside dentaquestJobs ---
let currentFinalSessionId: string | null = null;
let currentFinalResult: any = null;

function now() {
  return new Date().toISOString();
}
function log(tag: string, msg: string, ctx?: any) {
  console.log(`${now()} [${tag}] ${msg}`, ctx ?? "");
}

function emitSafe(socketId: string | undefined, event: string, payload: any) {
  if (!socketId) {
    log("socket", "no socketId for emit", { event });
    return;
  }
  try {
    const socket = io?.sockets.sockets.get(socketId);
    if (!socket) {
      log("socket", "socket not found (maybe disconnected)", {
        socketId,
        event,
      });
      return;
    }
    socket.emit(event, payload);
    log("socket", "emitted", { socketId, event });
  } catch (err: any) {
    log("socket", "emit failed", { socketId, event, err: err?.message });
  }
}

/**
 * Polls Python agent for session status and emits socket events:
 *  - 'selenium:otp_required' when waiting_for_otp
 *  - 'selenium:session_update' when completed/error
 *  - absolute timeout + transient error handling.
 *  - pollTimeoutMs default = 2 minutes (adjust where invoked)
 */
async function pollAgentSessionAndProcess(
  sessionId: string,
  socketId?: string,
  pollTimeoutMs = 2 * 60 * 1000
) {
  const maxAttempts = 300;
  const baseDelayMs = 1000;
  const maxTransientErrors = 12;

  // NEW: give up if same non-terminal status repeats this many times
  const noProgressLimit = 100;

  const job = dentaquestJobs[sessionId];
  let transientErrorCount = 0;
  let consecutiveNoProgress = 0;
  let lastStatus: string | null = null;
  const deadline = Date.now() + pollTimeoutMs;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    // absolute deadline check
    if (Date.now() > deadline) {
      emitSafe(socketId, "selenium:session_update", {
        session_id: sessionId,
        status: "error",
        message: `Polling timeout reached (${Math.round(pollTimeoutMs / 1000)}s).`,
      });
      delete dentaquestJobs[sessionId];
      return;
    }

    log(
      "poller",
      `attempt=${attempt} session=${sessionId} transientErrCount=${transientErrorCount}`
    );

    try {
      const st = await getSeleniumDentaQuestSessionStatus(sessionId);
      const status = st?.status ?? null;
      log("poller", "got status", {
        sessionId,
        status,
        message: st?.message,
        resultKeys: st?.result ? Object.keys(st.result) : null,
      });

      // reset transient errors on success
      transientErrorCount = 0;

      // if status unchanged and non-terminal, increment no-progress counter
      const isTerminalLike =
        status === "completed" || status === "error" || status === "not_found";
      if (status === lastStatus && !isTerminalLike) {
        consecutiveNoProgress++;
      } else {
        consecutiveNoProgress = 0;
      }
      lastStatus = status;

      // if no progress for too many consecutive polls -> abort
      if (consecutiveNoProgress >= noProgressLimit) {
        emitSafe(socketId, "selenium:session_update", {
          session_id: sessionId,
          status: "error",
          message: `No progress from selenium agent (status="${status}") after ${consecutiveNoProgress} polls; aborting.`,
        });
        emitSafe(socketId, "selenium:session_error", {
          session_id: sessionId,
          status: "error",
          message: "No progress from selenium agent",
        });
        delete dentaquestJobs[sessionId];
        return;
      }

      // always emit debug to client if socket exists
      emitSafe(socketId, "selenium:debug", {
        session_id: sessionId,
        attempt,
        status,
        serverTime: new Date().toISOString(),
      });

      // If agent is waiting for OTP, inform client but keep polling (do not return)
      if (status === "waiting_for_otp") {
        emitSafe(socketId, "selenium:otp_required", {
          session_id: sessionId,
          message: "OTP required. Please enter the OTP.",
        });
        // do not return — keep polling (allows same poller to pick up completion)
        await new Promise((r) => setTimeout(r, baseDelayMs));
        continue;
      }

      // Completed path
      if (status === "completed") {
        log("poller", "agent completed; processing result", {
          sessionId,
          resultKeys: st.result ? Object.keys(st.result) : null,
        });

        // Persist raw result so frontend can fetch if socket disconnects
        currentFinalSessionId = sessionId;
        currentFinalResult = {
          rawSelenium: st.result,
          processedAt: null,
          final: null,
        };

        let finalResult: any = null;
        if (job && st.result) {
          try {
            finalResult = await handleDentaQuestCompletedJob(
              sessionId,
              job,
              st.result
            );
            currentFinalResult.final = finalResult;
            currentFinalResult.processedAt = Date.now();
          } catch (err: any) {
            currentFinalResult.final = {
              error: "processing_failed",
              detail: err?.message ?? String(err),
            };
            currentFinalResult.processedAt = Date.now();
            log("poller", "handleDentaQuestCompletedJob failed", {
              sessionId,
              err: err?.message ?? err,
            });
          }
        } else {
          currentFinalResult.final = {
            error: "no_job_or_no_result",
          };
          currentFinalResult.processedAt = Date.now();
        }

        // Emit final update (if socket present)
        emitSafe(socketId, "selenium:session_update", {
          session_id: sessionId,
          status: "completed",
          rawSelenium: st.result,
          final: currentFinalResult.final,
        });

        // cleanup job context
        delete dentaquestJobs[sessionId];
        return;
      }

      // Terminal error / not_found
      if (status === "error" || status === "not_found") {
        const emitPayload = {
          session_id: sessionId,
          status,
          message: st?.message || "Selenium session error",
        };
        emitSafe(socketId, "selenium:session_update", emitPayload);
        emitSafe(socketId, "selenium:session_error", emitPayload);
        delete dentaquestJobs[sessionId];
        return;
      }
    } catch (err: any) {
      const axiosStatus =
        err?.response?.status ?? (err?.status ? Number(err.status) : undefined);
      const errCode = err?.code ?? err?.errno;
      const errMsg = err?.message ?? String(err);
      const errData = err?.response?.data ?? null;

      // If agent explicitly returned 404 -> terminal (session gone)
      if (
        axiosStatus === 404 ||
        (typeof errMsg === "string" && errMsg.includes("not_found"))
      ) {
        console.warn(
          `${new Date().toISOString()} [poller] terminal 404/not_found for ${sessionId}: data=${JSON.stringify(errData)}`
        );

        // Emit not_found to client
        const emitPayload = {
          session_id: sessionId,
          status: "not_found",
          message:
            errData?.detail || "Selenium session not found (agent cleaned up).",
        };
        emitSafe(socketId, "selenium:session_update", emitPayload);
        emitSafe(socketId, "selenium:session_error", emitPayload);

        // Remove job context and stop polling
        delete dentaquestJobs[sessionId];
        return;
      }

      // Detailed transient error logging
      transientErrorCount++;
      if (transientErrorCount > maxTransientErrors) {
        const emitPayload = {
          session_id: sessionId,
          status: "error",
          message:
            "Repeated network errors while polling selenium agent; giving up.",
        };
        emitSafe(socketId, "selenium:session_update", emitPayload);
        emitSafe(socketId, "selenium:session_error", emitPayload);
        delete dentaquestJobs[sessionId];
        return;
      }

      const backoffMs = Math.min(
        30_000,
        baseDelayMs * Math.pow(2, transientErrorCount - 1)
      );
      console.warn(
        `${new Date().toISOString()} [poller] transient error (#${transientErrorCount}) for ${sessionId}: code=${errCode} status=${axiosStatus} msg=${errMsg} data=${JSON.stringify(errData)}`
      );
      console.warn(
        `${new Date().toISOString()} [poller] backing off ${backoffMs}ms before next attempt`
      );

      await new Promise((r) => setTimeout(r, backoffMs));
      continue;
    }

    // normal poll interval
    await new Promise((r) => setTimeout(r, baseDelayMs));
  }

  // overall timeout fallback
  emitSafe(socketId, "selenium:session_update", {
    session_id: sessionId,
    status: "error",
    message: "Polling timeout while waiting for selenium session",
  });
  delete dentaquestJobs[sessionId];
}

/**
 * POST /dentaquest-eligibility
 * Starts DentaQuest eligibility Selenium job.
 * Expects:
 *  - req.body.data: stringified JSON like your existing /eligibility-check
 *  - req.body.socketId: socket.io client id
 */
router.post(
  "/dentaquest-eligibility",
  async (req: Request, res: Response): Promise<any> => {
    if (!req.body.data) {
      return res
        .status(400)
        .json({ error: "Missing Insurance Eligibility data for selenium" });
    }

    if (!req.user || !req.user.id) {
      return res.status(401).json({ error: "Unauthorized: user info missing" });
    }

    try {
      const rawData =
        typeof req.body.data === "string"
          ? JSON.parse(req.body.data)
          : req.body.data;

      const credentials = await storage.getInsuranceCredentialByUserAndSiteKey(
        req.user.id,
        rawData.insuranceSiteKey
      );
      if (!credentials) {
        return res.status(404).json({
          error:
            "No insurance credentials found for this provider, Kindly Update this at Settings Page.",
        });
      }

      const enrichedData = {
        ...rawData,
        dentaquestUsername: credentials.username,
        dentaquestPassword: credentials.password,
      };

      const socketId: string | undefined = req.body.socketId;

      const agentResp =
        await forwardToSeleniumDentaQuestEligibilityAgent(enrichedData);

      if (
        !agentResp ||
        agentResp.status !== "started" ||
        !agentResp.session_id
      ) {
        return res.status(502).json({
          error: "Selenium agent did not return a started session",
          detail: agentResp,
        });
      }

      const sessionId = agentResp.session_id as string;

      // Save job context
      dentaquestJobs[sessionId] = {
        userId: req.user.id,
        insuranceEligibilityData: enrichedData,
        socketId,
      };

      // start polling in background to notify client via socket and process job
      pollAgentSessionAndProcess(sessionId, socketId).catch((e) =>
        console.warn("pollAgentSessionAndProcess failed", e)
      );

      // reply immediately with started status
      return res.json({ status: "started", session_id: sessionId });
    } catch (err: any) {
      console.error(err);
      return res.status(500).json({
        error: err.message || "Failed to start DentaQuest selenium agent",
      });
    }
  }
);

/**
 * POST /selenium/submit-otp
 * Body: { session_id, otp, socketId? }
 * Forwards OTP to Python agent and optionally notifies client socket.
 */
router.post(
  "/selenium/submit-otp",
  async (req: Request, res: Response): Promise<any> => {
    const { session_id: sessionId, otp, socketId } = req.body;
    if (!sessionId || !otp) {
      return res.status(400).json({ error: "session_id and otp are required" });
    }

    try {
      const r = await forwardOtpToSeleniumDentaQuestAgent(sessionId, otp);

      // emit OTP accepted (if socket present)
      emitSafe(socketId, "selenium:otp_submitted", {
        session_id: sessionId,
        result: r,
      });

      return res.json(r);
    } catch (err: any) {
      console.error(
        "Failed to forward OTP:",
        err?.response?.data || err?.message || err
      );
      return res.status(500).json({
        error: "Failed to forward otp to selenium agent",
        detail: err?.message || err,
      });
    }
  }
);

// GET /selenium/session/:sid/final
router.get(
  "/selenium/session/:sid/final",
  async (req: Request, res: Response) => {
    const sid = req.params.sid;
    if (!sid) return res.status(400).json({ error: "session id required" });

    // Only the current in-memory result is available
    if (currentFinalSessionId !== sid || !currentFinalResult) {
      return res.status(404).json({ error: "final result not found" });
    }

    return res.json(currentFinalResult);
  }
);

export default router;

