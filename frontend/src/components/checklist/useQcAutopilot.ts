import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import { getAutopilotJob, startAutopilot } from "../../api/client";
import type { AutopilotJob } from "../../types";
import { getApiErrorMessage } from "../../utils/apiErrors";

type UseQcAutopilotOptions = {
  caseId: string;
  reload: () => Promise<void>;
};

export function useQcAutopilot({ caseId, reload }: UseQcAutopilotOptions) {
  const [autopilotJob, setAutopilotJob] = useState<AutopilotJob | null>(null);
  const [verifyingCl, setVerifyingCl] = useState<string | null>(null);
  const autopilotPollRef = useRef<number | null>(null);
  const autopilotStorageKey = `qc-autopilot:${caseId}`;

  const clearAutopilotSession = () => {
    if (typeof window === "undefined") return;
    window.sessionStorage.removeItem(autopilotStorageKey);
  };

  const saveAutopilotSession = (checklistId: string, jobId: string) => {
    if (typeof window === "undefined") return;
    window.sessionStorage.setItem(
      autopilotStorageKey,
      JSON.stringify({ checklistId, jobId })
    );
  };

  const readAutopilotSession = (): { checklistId: string; jobId: string } | null => {
    if (typeof window === "undefined") return null;

    const raw = window.sessionStorage.getItem(autopilotStorageKey);
    if (!raw) return null;

    try {
      const parsed = JSON.parse(raw) as {
        checklistId?: unknown;
        jobId?: unknown;
      };

      if (typeof parsed.checklistId !== "string" || typeof parsed.jobId !== "string") {
        clearAutopilotSession();
        return null;
      }

      return {
        checklistId: parsed.checklistId,
        jobId: parsed.jobId,
      };
    } catch {
      clearAutopilotSession();
      return null;
    }
  };

  const clearAutopilotPoll = () => {
    if (autopilotPollRef.current !== null) {
      window.clearTimeout(autopilotPollRef.current);
      autopilotPollRef.current = null;
    }
  };

  const nextAutopilotPollDelay = (phase?: string) => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return 10000;
    }
    if (
      phase === "extracting_document" ||
      phase === "writing_json" ||
      phase === "indexing_document"
    ) {
      return 5000;
    }
    return 2500;
  };

  const pollAutopilotJob = (jobId: string, checklistId: string) => {
    const tick = async () => {
      try {
        const job = await getAutopilotJob(jobId);
        setAutopilotJob(job);
        if (job.status === "completed") {
          clearAutopilotPoll();
          clearAutopilotSession();
          setAutopilotJob({ ...job, phase: "loading_results" });

          if (job.verified === 0 && job.skipped > 0) {
            toast.error(
              `AI Autopilot: ${job.skipped} questions skipped. Questions need linked pages (evidence or mapped sections with classified pages).`,
              { duration: 8000 }
            );
          } else if (job.verified > 0) {
            toast.success(
              `AI Autopilot completed: ${job.verified} verified` +
                (job.skipped > 0 ? `, ${job.skipped} skipped (no pages)` : "") +
                (job.errors > 0 ? `, ${job.errors} errors` : "")
            );
          } else {
            toast.success("AI Autopilot completed");
          }
          await reload();
          setVerifyingCl(null);
          setAutopilotJob(null);
        } else if (job.status === "failed") {
          clearAutopilotPoll();
          clearAutopilotSession();
          setVerifyingCl(null);
          toast.error(`AI Autopilot failed: ${job.error_message || "unknown error"}`);
          setAutopilotJob(null);
        } else {
          autopilotPollRef.current = window.setTimeout(() => {
            void tick();
          }, nextAutopilotPollDelay(job.phase));
        }
      } catch {
        clearAutopilotPoll();
        setVerifyingCl(null);
        setAutopilotJob(null);
      }
    };

    setVerifyingCl(checklistId);
    autopilotPollRef.current = window.setTimeout(() => {
      void tick();
    }, nextAutopilotPollDelay("loading_questions"));
  };

  const handleAIVerifyChecklist = async (checklistId: string) => {
    clearAutopilotPoll();
    setVerifyingCl(checklistId);
    try {
      const job = await startAutopilot(checklistId);
      saveAutopilotSession(checklistId, job.id);
      setAutopilotJob(job);
      toast.success("AI Autopilot started");
      pollAutopilotJob(job.id, checklistId);
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "Failed to start AI Autopilot"));
      setVerifyingCl(null);
    }
  };

  useEffect(() => {
    const restoreAutopilotSession = async () => {
      const savedSession = readAutopilotSession();
      if (!savedSession) return;

      try {
        const job = await getAutopilotJob(savedSession.jobId);
        if (job.status === "queued" || job.status === "running") {
          clearAutopilotPoll();
          setVerifyingCl(savedSession.checklistId);
          setAutopilotJob(job);
          pollAutopilotJob(savedSession.jobId, savedSession.checklistId);
          return;
        }

        clearAutopilotSession();
      } catch {
        // Keep the saved job reference so the UI can retry restoring it later.
      }
    };

    void restoreAutopilotSession();
    return () => clearAutopilotPoll();
  }, [caseId]);

  return {
    autopilotJob,
    verifyingCl,
    handleAIVerifyChecklist,
  };
}
