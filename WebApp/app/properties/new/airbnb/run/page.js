import AddPropertyWizard from "../../../../../components/AddPropertyWizard";

export default async function AirbnbRunPage({ searchParams }) {
  const params = await searchParams;
  return <AddPropertyWizard view="run" propertyId={params?.propertyId || ""} runId={params?.runId || ""} />;
}
