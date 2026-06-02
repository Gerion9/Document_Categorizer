import { useCallback, useState } from "react";

import { Loader2 } from "lucide-react";

import toast from "react-hot-toast";

import { motion, AnimatePresence } from "framer-motion";

import { uploadFiles } from "../api/client";

import { AnimatedUpload } from "./ui/AnimatedUpload";

import type { Page } from "../types";

import { getApiErrorMessage } from "../utils/apiErrors";



interface Props {

  caseId: string;

  onUploaded: (pages: Page[]) => void;

}



export default function FileUpload({ caseId, onUploaded }: Props) {

  const [dragging, setDragging] = useState(false);

  const [uploading, setUploading] = useState(false);



  const handleFiles = useCallback(

    async (fileList: FileList | null) => {

      if (!fileList || fileList.length === 0) return;

      const files = Array.from(fileList);

      setUploading(true);

      try {

        const pages = await uploadFiles(caseId, files);

        toast.success(`${pages.length} pagina(s) cargadas`);

        onUploaded(pages);

      } catch (error: unknown) {

        toast.error(getApiErrorMessage(error, "Error al subir archivos"));

      } finally {

        setUploading(false);

      }

    },

    [caseId, onUploaded]

  );



  const onDrop = useCallback(

    (e: React.DragEvent) => {

      e.preventDefault();

      setDragging(false);

      handleFiles(e.dataTransfer.files);

    },

    [handleFiles]

  );



  return (

    <motion.div

      whileHover={{ scale: dragging ? 1 : 1.01 }}

      whileTap={{ scale: 0.99 }}

      animate={{

        borderColor: dragging ? "rgba(20, 52, 87, 0.45)" : "rgba(20, 52, 87, 0.15)",

        backgroundColor: dragging ? "rgba(232, 241, 248, 0.95)" : "rgba(255, 255, 255, 0.75)",

      }}

      transition={{ duration: 0.2 }}

      onDragOver={(e) => {

        e.preventDefault();

        setDragging(true);

      }}

      onDragLeave={() => setDragging(false)}

      onDrop={onDrop}

      className="solid-panel relative rounded-2xl border-2 border-dashed p-10 text-center cursor-pointer select-none overflow-hidden shadow-sm hover:shadow-md opacity-[0.96]"

      onClick={() => {

        if (uploading) return;

        const input = document.createElement("input");

        input.type = "file";

        input.multiple = true;

        input.accept = ".pdf,.jpg,.jpeg,.png,.gif,.bmp,.tiff,.tif,.webp";

        input.onchange = () => handleFiles(input.files);

        input.click();

      }}

    >

      <AnimatePresence>

        {dragging && (

          <motion.div

            initial={{ opacity: 0, scale: 0.8 }}

            animate={{ opacity: 1, scale: 1 }}

            exit={{ opacity: 0, scale: 0.8 }}

            className="absolute inset-0 bg-brand-500/5 rounded-2xl pointer-events-none"

          />

        )}

      </AnimatePresence>



      <div className="relative z-10 flex flex-col items-center justify-center gap-3">

        <motion.div

          animate={{ y: dragging ? -5 : 0 }}

          className={`p-4 rounded-full ${dragging ? "bg-brand-100" : "bg-brand-50"}`}

        >

          {uploading ? (

            <Loader2 className="w-10 h-10 text-brand-500 animate-spin" />

          ) : (

            <AnimatedUpload className={`w-10 h-10 ${dragging ? "text-brand-500" : "text-brand-400"}`} isDragging={dragging} />

          )}

        </motion.div>



        <div>

          <p className={`text-base font-semibold ${dragging ? "text-brand-700" : "text-brand-800"}`}>

            {uploading

              ? "Procesando archivos…"

              : dragging

              ? "Suelta los archivos aquí"

              : "Haz clic o arrastra archivos aquí"}

          </p>

          <p className="text-xs text-brand-500 mt-1">

            Soporta documentos PDF y formatos de imagen estándar

          </p>

        </div>

      </div>

    </motion.div>

  );

}

