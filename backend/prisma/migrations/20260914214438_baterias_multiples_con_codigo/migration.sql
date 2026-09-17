/*
  Warnings:

  - A unique constraint covering the columns `[codigoActivacion]` on the table `Bateria` will be added. If there are existing duplicate values, this will fail.

*/
-- DropIndex
DROP INDEX "Bateria_sistemaId_key";

-- AlterTable
ALTER TABLE "Bateria" ADD COLUMN     "codigoActivacion" TEXT;

-- CreateIndex
CREATE UNIQUE INDEX "Bateria_codigoActivacion_key" ON "Bateria"("codigoActivacion");
