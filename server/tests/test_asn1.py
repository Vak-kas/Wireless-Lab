"""ASN.1 왕복(인코드 -> 디코드)."""

from nrtrail import mockraw
from nrtrail.asn1 import rrc, samples


def test_mib_roundtrip_and_known_bytes():
    value = samples.mib(25, "scs15or60", 4, "pos2", 100)
    data = rrc.encode("BCCH-BCH-Message", value)
    assert data.hex() == "324324"  # MATLAB 합성기가 만든 PBCH 페이로드(pipeline/golden/ntn-leo-n256)와 같다
    decoded, _ = rrc.decode("BCCH-BCH-Message", data)
    assert decoded == value


def test_sib1_roundtrip_with_r17_extension():
    value = samples.bcch_dl_sch_sib1(samples.sib1(band=256, scs="kHz15", carrier_rbs=25, offset_to_point_a=2,
                                                  loc_and_bw=6600, ntn=True, ssb_positions=0b11000000))
    data = rrc.encode("BCCH-DL-SCH-Message", value)
    decoded, tree = rrc.decode("BCCH-DL-SCH-Message", data)
    assert decoded == value
    ext = rrc.find_path(decoded, "message", "c1", "systemInformationBlockType1", "nonCriticalExtension",
                        "nonCriticalExtension", "nonCriticalExtension")
    assert ext["cellBarredNTN-r17"] == "notBarred"
    assert tree["message"]["c1"]["systemInformationBlockType1"]["cellSelectionInfo"]["q-RxLevMin"] == -62


def test_sib19_roundtrip_survives_padding():
    value = samples.bcch_dl_sch_si([("sib19-v1700", samples.sib19(**mockraw.SIB19_SAMPLE))])
    data = rrc.encode("BCCH-DL-SCH-Message", value)
    decoded, _ = rrc.decode("BCCH-DL-SCH-Message", data + b"\x00\x00\x00")
    assert decoded == value


def test_truncated_message_raises():
    import pytest

    data = rrc.encode("BCCH-DL-SCH-Message", samples.bcch_dl_sch_sib1(samples.sib1(
        band=256, scs="kHz15", carrier_rbs=25, offset_to_point_a=2, loc_and_bw=6600, ntn=True, ssb_positions=192)))
    for cut in (0, 5, 40):
        with pytest.raises(rrc.Asn1Error):
            rrc.decode("BCCH-DL-SCH-Message", data[:cut])
