-- CreateTable
CREATE TABLE "Bateria" (
    "id" SERIAL NOT NULL,
    "capacidadKwh" DOUBLE PRECISION NOT NULL,
    "fechaInstalacion" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "sistemaId" INTEGER NOT NULL,

    CONSTRAINT "Bateria_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Bateria_sistemaId_key" ON "Bateria"("sistemaId");

-- AddForeignKey
ALTER TABLE "Bateria" ADD CONSTRAINT "Bateria_sistemaId_fkey" FOREIGN KEY ("sistemaId") REFERENCES "Sistema"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
