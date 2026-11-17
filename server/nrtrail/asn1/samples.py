"""합성 파형과 연습 모드에 넣는 '알려진 값'(정답). 실제 사업자·위성과 무관한 시험용 값이다.

여기서 만든 값이 ASN.1로 인코드되어 파형에 실리고, 복호 결과와 정확히 같아야 한다(SPEC 13절).
"""

from __future__ import annotations

from typing import Any

from . import rrc


def mib(sfn_msb6: int, scs_common: str, k_ssb_lsb4: int, dmrs_pos: str, pdcch_config_sib1: int,
        barred: bool = False, intra_freq: bool = True) -> dict[str, Any]:
    return {
        "message": ("mib", {
            "systemFrameNumber": (sfn_msb6, 6),
            "subCarrierSpacingCommon": scs_common,
            "ssb-SubcarrierOffset": k_ssb_lsb4,
            "dmrs-TypeA-Position": dmrs_pos,
            "pdcch-ConfigSIB1": {"controlResourceSetZero": pdcch_config_sib1 >> 4,
                                 "searchSpaceZero": pdcch_config_sib1 & 0xF},
            "cellBarred": "barred" if barred else "notBarred",
            "intraFreqReselection": "allowed" if intra_freq else "notAllowed",
            "spare": (0, 1),
        })
    }


def sib1(*, band: int, scs: str, carrier_rbs: int, offset_to_point_a: int, loc_and_bw: int,
         ntn: bool, ssb_positions: int, ssb_period: str = "ms20", ul_point_a_arfcn: int | None = None) -> dict[str, Any]:
    """SIB1. ntn=True면 SIB19를 Rel-17 확장 스케줄 목록에 싣고 cellBarredNTN을 넣는다."""
    generic = {"locationAndBandwidth": loc_and_bw, "subcarrierSpacing": scs}
    rach_generic = {
        "prach-ConfigurationIndex": 98, "msg1-FDM": "one", "msg1-FrequencyStart": 0,
        "zeroCorrelationZoneConfig": 13, "preambleReceivedTargetPower": -104,
        "preambleTransMax": "n10", "powerRampingStep": "dB2", "ra-ResponseWindow": "sl20",
    }
    rach = {
        "rach-ConfigGeneric": rach_generic,
        "ssb-perRACH-OccasionAndCB-PreamblesPerSSB": ("one", "n64"),
        "ra-ContentionResolutionTimer": "sf64",
        "prach-RootSequenceIndex": ("l839", 1),
        "msg1-SubcarrierSpacing": scs,
        "restrictedSetConfig": "unrestrictedSet",
    }
    serving = {
        "downlinkConfigCommon": {
            "frequencyInfoDL": {
                "frequencyBandList": [{"freqBandIndicatorNR": band}],
                "offsetToPointA": offset_to_point_a,
                "scs-SpecificCarrierList": [{"offsetToCarrier": 0, "subcarrierSpacing": scs, "carrierBandwidth": carrier_rbs}],
            },
            "initialDownlinkBWP": {
                "genericParameters": generic,
                "pdcch-ConfigCommon": ("setup", {"controlResourceSetZero": 0, "searchSpaceZero": 0,
                                                 "searchSpaceSIB1": 0, "searchSpaceOtherSystemInformation": 0,
                                                 "pagingSearchSpace": 0, "ra-SearchSpace": 0}),
                "pdsch-ConfigCommon": ("setup", {"pdsch-TimeDomainAllocationList": [
                    {"mappingType": "typeA", "startSymbolAndLength": 53}]}),
            },
            "bcch-Config": {"modificationPeriodCoeff": "n4"},
            "pcch-Config": {
                "defaultPagingCycle": "rf128", "nAndPagingFrameOffset": ("oneT", 0), "ns": "one",
            },
        },
        "uplinkConfigCommon": {
            "frequencyInfoUL": {
                "scs-SpecificCarrierList": [{"offsetToCarrier": 0, "subcarrierSpacing": scs, "carrierBandwidth": carrier_rbs}],
                "p-Max": 23,
            },
            "initialUplinkBWP": {
                "genericParameters": generic,
                "rach-ConfigCommon": ("setup", rach),
                "pusch-ConfigCommon": ("setup", {"pusch-TimeDomainAllocationList": [
                    {"k2": 6, "mappingType": "typeA", "startSymbolAndLength": 55}],
                    "msg3-DeltaPreamble": 1, "p0-NominalWithGrant": -90}),
                "pucch-ConfigCommon": ("setup", {"pucch-ResourceCommon": 0, "pucch-GroupHopping": "neither",
                                                 "p0-nominal": -90}),
            },
            "timeAlignmentTimerCommon": "infinity",
        },
        "n-TimingAdvanceOffset": "n0",
        "ssb-PositionsInBurst": {"inOneGroup": (ssb_positions, 8)},
        "ssb-PeriodicityServingCell": ssb_period,
        "ss-PBCH-BlockPower": 20,
    }
    if ul_point_a_arfcn is not None:
        serving["uplinkConfigCommon"]["frequencyInfoUL"]["absoluteFrequencyPointA"] = ul_point_a_arfcn  # type: ignore[index]
    msg: dict[str, Any] = {
        "cellSelectionInfo": {"q-RxLevMin": -62},
        "cellAccessRelatedInfo": {"plmn-IdentityInfoList": [{
            "plmn-IdentityList": [{"mcc": [0, 0, 1], "mnc": [0, 1]}],
            "trackingAreaCode": (0x000A01, 24),
            "cellIdentity": (0x00012345A, 36),
            "cellReservedForOperatorUse": "notReserved",
        }]},
        "connEstFailureControl": {"connEstFailCount": "n1", "connEstFailOffsetValidity": "s30"},
        "si-SchedulingInfo": {
            "schedulingInfoList": [{"si-BroadcastStatus": "broadcasting", "si-Periodicity": "rf16",
                                    "sib-MappingInfo": [{"type": "sibType2", "valueTag": 0}]}],
            "si-WindowLength": "s20",
        },
        "servingCellConfigCommon": serving,
        "ue-TimersAndConstants": {"t300": "ms1000", "t301": "ms1000", "t310": "ms1000", "n310": "n1",
                                  "t311": "ms3000", "n311": "n1", "t319": "ms1000"},
    }
    if ntn:
        v1700 = {
            "si-SchedulingInfo-v1700": {"schedulingInfoList2-r17": [{
                "si-BroadcastStatus-r17": "broadcasting", "si-WindowPosition-r17": 2, "si-Periodicity-r17": "rf8",
                "sib-MappingInfo-r17": [{"sibType-r17": ("type1-r17", "sibType19"), "valueTag-r17": 0}],
            }]},
            "cellBarredNTN-r17": "notBarred",
        }
        # SIB1의 Rel-17 확장은 nonCriticalExtension 사슬의 v1610 -> v1630 -> v1700 순서로 들어간다.
        msg["nonCriticalExtension"] = {"nonCriticalExtension": {"nonCriticalExtension": v1700}}
    return msg


def sib19(*, epoch_sfn: int, epoch_subframe: int, position: tuple[int, int, int],
          velocity: tuple[int, int, int], ta_common: int, ta_drift: int, ta_drift_variant: int,
          k_offset: int, validity: str = "s20", kmac: int | None = None,
          polarization: str = "rhcp", reference_location: bytes | None = None,
          distance_thresh: int | None = None, t_service: int | None = None) -> dict[str, Any]:
    ntn_config: dict[str, Any] = {
        "epochTime-r17": {"sfn-r17": epoch_sfn, "subFrameNR-r17": epoch_subframe},
        "ntn-UlSyncValidityDuration-r17": validity,
        "cellSpecificKoffset-r17": k_offset,
        "ta-Info-r17": {"ta-Common-r17": ta_common, "ta-CommonDrift-r17": ta_drift,
                        "ta-CommonDriftVariant-r17": ta_drift_variant},
        "ntn-PolarizationDL-r17": polarization,
        "ephemerisInfo-r17": ("positionVelocity-r17", {
            "positionX-r17": position[0], "positionY-r17": position[1], "positionZ-r17": position[2],
            "velocityVX-r17": velocity[0], "velocityVY-r17": velocity[1], "velocityVZ-r17": velocity[2],
        }),
    }
    if kmac is not None:
        ntn_config["kmac-r17"] = kmac
    msg: dict[str, Any] = {"ntn-Config-r17": ntn_config}
    if t_service is not None:
        msg["t-Service-r17"] = t_service
    if reference_location is not None:
        msg["referenceLocation-r17"] = reference_location
    if distance_thresh is not None:
        msg["distanceThresh-r17"] = distance_thresh
    return msg


def bcch_dl_sch_sib1(sib1_value: dict[str, Any]) -> dict[str, Any]:
    return {"message": ("c1", ("systemInformationBlockType1", sib1_value))}


def bcch_dl_sch_si(sibs: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """SI 메시지 하나. sibs는 (CHOICE 이름, 값) 목록. sib19-v1700 같은 Rel-17 SIB는 확장 CHOICE에 들어간다."""
    return {"message": ("c1", ("systemInformation", {"criticalExtensions": ("systemInformation", {
        "sib-TypeAndInfo": list(sibs)})}))}


def encode_hex(message: str, value: Any) -> str:
    return rrc.encode(message, value).hex()
