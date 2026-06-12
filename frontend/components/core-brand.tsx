import Image from "next/image";

import coreLogo from "@/logo/corelogo.png";

type CoreBrandProps = Readonly<{
  compact?: boolean;
  subtitle?: string;
}>;

export function CoreBrand({ compact = false, subtitle = "Control Centre" }: Readonly<CoreBrandProps>) {
  return (
    <div className={`core-brand ${compact ? "compact" : ""}`}>
      <Image src={coreLogo} alt="Core logo" className="core-brand-logo" priority={compact} />
      <div>
        <p className="core-brand-title">CORE</p>
        <p className="core-brand-subtitle">{subtitle}</p>
      </div>
    </div>
  );
}
