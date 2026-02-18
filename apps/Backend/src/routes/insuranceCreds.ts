import express, { Request, Response } from "express";
import { storage } from "../storage";
import { z } from "zod";
import {
  insertInsuranceCredentialSchema,
  InsuranceCredential,
} from "@repo/db/types";

const router = express.Router();

// ✅ Get all credentials for a user
router.get("/", async (req: Request, res: Response): Promise<any> => {
  try {
    if (!req.user || !req.user.id) {
      return res
        .status(401)
        .json({ message: "Unauthorized: user info missing" });
    }
    const userId = req.user.id;

    const credentials = await storage.getInsuranceCredentialsByUser(userId);
    return res.status(200).json(credentials);
  } catch (err) {
    return res
      .status(500)
      .json({ error: "Failed to fetch credentials", details: String(err) });
  }
});

// ✅ Create credential for a user
router.post("/", async (req: Request, res: Response): Promise<any> => {
  try {
    if (!req.user || !req.user.id) {
      return res
        .status(401)
        .json({ message: "Unauthorized: user info missing" });
    }
    const userId = req.user.id;

    const parseResult = insertInsuranceCredentialSchema.safeParse({
      ...req.body,
      userId,
    });
    if (!parseResult.success) {
      const flat = (
        parseResult as typeof parseResult & { error: z.ZodError<any> }
      ).error.flatten();
      const firstError =
        Object.values(flat.fieldErrors)[0]?.[0] || "Invalid input";

      return res.status(400).json({
        message: firstError,
        details: flat.fieldErrors,
      });
    }

    const credential = await storage.createInsuranceCredential(
      parseResult.data
    );
    return res.status(201).json(credential);
  } catch (err: any) {
    if (err.code === "P2002") {
      return res.status(400).json({
        message: `Credential with this ${err.meta?.target?.join(", ")} already exists.`,
      });
    }
    return res
      .status(500)
      .json({ error: "Failed to create credential", details: String(err) });
  }
});

// ✅ Update credential
router.put("/:id", async (req: Request, res: Response): Promise<any> => {
  try {
    const id = Number(req.params.id);
    if (isNaN(id)) return res.status(400).send("Invalid credential ID");

    // Get existing credential to know its siteKey
    const existing = await storage.getInsuranceCredential(id);
    if (!existing) {
      return res.status(404).json({ message: "Credential not found" });
    }

    const updates = req.body as Partial<InsuranceCredential>;
    const credential = await storage.updateInsuranceCredential(id, updates);

    // Clear Selenium browser session when credentials are changed
    const seleniumAgentUrl = process.env.SELENIUM_AGENT_URL || "http://localhost:5002";
    try {
      if (existing.siteKey === "DDMA") {
        await fetch(`${seleniumAgentUrl}/clear-ddma-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared DDMA browser session after credential update");
      } else if (existing.siteKey === "DENTAQUEST") {
        await fetch(`${seleniumAgentUrl}/clear-dentaquest-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared DentaQuest browser session after credential update");
      } else if (existing.siteKey === "UNITEDSCO") {
        await fetch(`${seleniumAgentUrl}/clear-unitedsco-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared United SCO browser session after credential update");
      } else if (existing.siteKey === "DELTAINS") {
        await fetch(`${seleniumAgentUrl}/clear-deltains-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared Delta Dental Ins browser session after credential update");
      }
    } catch (seleniumErr) {
      // Don't fail the update if Selenium session clear fails
      console.error("[insuranceCreds] Failed to clear Selenium session:", seleniumErr);
    }

    return res.status(200).json(credential);
  } catch (err) {
    return res
      .status(500)
      .json({ error: "Failed to update credential", details: String(err) });
  }
});

// ✅ Delete a credential
router.delete("/:id", async (req: Request, res: Response): Promise<any> => {
  try {
    const userId = (req as any).user?.id;
    if (!userId) return res.status(401).json({ message: "Unauthorized" });

    const id = Number(req.params.id);
    if (isNaN(id)) return res.status(400).send("Invalid ID");

    // 1) Check existence
    const existing = await storage.getInsuranceCredential(id);
    if (!existing)
      return res.status(404).json({ message: "Credential not found" });

    // 2) Ownership check
    if (existing.userId !== userId) {
      return res.status(403).json({
        message:
          "Forbidden: Credentials belongs to a different user, you can't delete this.",
      });
    }

    // 3) Delete (storage method enforces userId + id)
    const ok = await storage.deleteInsuranceCredential(userId, id);
    if (!ok) {
      return res
        .status(404)
        .json({ message: "Credential not found or already deleted" });
    }

    // 4) Clear Selenium browser session for this provider
    const seleniumAgentUrl = process.env.SELENIUM_AGENT_URL || "http://localhost:5002";
    try {
      if (existing.siteKey === "DDMA") {
        await fetch(`${seleniumAgentUrl}/clear-ddma-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared DDMA browser session after credential deletion");
      } else if (existing.siteKey === "DENTAQUEST") {
        await fetch(`${seleniumAgentUrl}/clear-dentaquest-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared DentaQuest browser session after credential deletion");
      } else if (existing.siteKey === "UNITEDSCO") {
        await fetch(`${seleniumAgentUrl}/clear-unitedsco-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared United SCO browser session after credential deletion");
      } else if (existing.siteKey === "DELTAINS") {
        await fetch(`${seleniumAgentUrl}/clear-deltains-session`, { method: "POST" });
        console.log("[insuranceCreds] Cleared Delta Dental Ins browser session after credential deletion");
      }
    } catch (seleniumErr) {
      // Don't fail the delete if Selenium session clear fails
      console.error("[insuranceCreds] Failed to clear Selenium session:", seleniumErr);
    }

    return res.status(204).send();
  } catch (err) {
    return res
      .status(500)
      .json({ error: "Failed to delete credential", details: String(err) });
  }
});

export default router;
