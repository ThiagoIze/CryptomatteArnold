#
#
#  Copyright (c) 2014, 2015, 2016, 2017 Psyop Media Company, LLC
#  See license.txt
#
#
import tests
import os
import json
import tempfile
import unittest

import arnold as ai

def get_all_cryptomatte_tests():
    return [
        Cryptomatte000, Cryptomatte001, Cryptomatte002, Cryptomatte003,
        Cryptomatte010, Cryptomatte020, Cryptomatte030, CryptomatteSetup
    ]


#############################################
# Cryptomatte test base class
#############################################

class CryptomatteTestBase(tests.KickAndCompareTestCase):
    ass = ""

    def setUp(self):
        self._result_images = []
        self._exr_result_images = []

    def load_results(self):
        for file_name in self.correct_file_names:
            img, correct_img = self.load_images(file_name)
            if img and correct_img:
                self._result_images.append((img, correct_img))
                if file_name.lower().endswith(".exr"):
                    self._exr_result_images.append((img, correct_img))

    @property
    def result_images(self):
        if not self._result_images:
            self.load_results()
        return self._result_images

    @property
    def exr_result_images(self):
        if not self._exr_result_images:
            self.load_results()
        return self._exr_result_images


    def crypto_metadata(self, ibuf):
        """Returns dictionary of key, value of cryptomatte metadata"""
        metadata = {
            a.name: a.value
            for a in ibuf.spec().extra_attribs
            if a.name.startswith("cryptomatte")
        }

        for key in metadata.keys():
            if key.endswith("/manif_file"):
                sidecar_path = os.path.join(
                    os.path.dirname(ibuf.name), metadata[key])
                with open(sidecar_path) as f:
                    metadata[key.replace("manif_file", "manifest")] = f.read()

        return metadata

    def sorted_crypto_metadata(self, img):
        """
        Gets a dictionary of the cryptomatte metadata, interleved by cryptomatte stream.

        for example:
            {"crypto_object": {"name": crypto_object", ... }}

        Also includes ID coverage pairs in subkeys, "ch_pair_idxs" and "ch_pair_names".
        """
        img_md = self.crypto_metadata(img)
        cryptomatte_streams = {}
        for key, value in img_md.iteritems():
            prefix, cryp_key, cryp_md_key = key.split("/")
            name = img_md["/".join((prefix, cryp_key, "name"))]
            cryptomatte_streams[name] = cryptomatte_streams.get(name, {})
            cryptomatte_streams[name][cryp_md_key] = value

        for cryp_key in cryptomatte_streams:
            name = cryptomatte_streams[cryp_key]["name"]
            ch_id_coverages = []
            ch_id_coverage_names = []
            channels_dict = {
                ch: i
                for i, ch in enumerate(img.spec().channelnames)
            }
            for i, ch in enumerate(img.spec().channelnames):
                if not ch.startswith(name):
                    continue
                if ch.startswith("%s." % name):
                    continue
                if ch.endswith(".R"):
                    red_name = ch
                    green_name = "%s.G" % ch[:-2]
                    blue_name = "%s.B" % ch[:-2]
                    alpha_name = "%s.A" % ch[:-2]

                    red_idx = i
                    green_idx = channels_dict[green_name]
                    blue_idx = channels_dict[blue_name]
                    alpha_idx = channels_dict[alpha_name]

                    ch_id_coverages.append((red_idx, green_idx))
                    ch_id_coverages.append((blue_idx, alpha_idx))
                    ch_id_coverage_names.append((red_name, green_name))
                    ch_id_coverage_names.append((blue_name, alpha_name))
            cryptomatte_streams[cryp_key]["ch_pair_idxs"] = ch_id_coverages
            cryptomatte_streams[cryp_key]["ch_pair_names"] = ch_id_coverage_names
        return cryptomatte_streams

    def assertManifestsAreValidAndMatch(self, result_md, correct_md, key):
        """ Does a comparison between two manifests. Order is not important, but contents are.
        Checks both are parsable with json
        Checks that there are no extra names in either manifest
        """
        try:
            correct_manifest = json.loads(correct_md[key])
        except Exception, e:
            raise RuntimeError("Correct manifest could not be loaded. %s" % e)
        try:
            result_manifest = json.loads(result_md[key])
        except Exception, e:
            self.fail("Result manifest could not be loaded. %s" % e)

        # test manifest hashes?
        correct_names = set(correct_manifest.keys())
        result_names = set(result_manifest.keys())

        if not result_manifest:
            self.fail("%s - Result manifest is empty. " % key)
        extra_in_correct = correct_names - result_names
        extra_in_result = result_names - correct_names
        if extra_in_correct or extra_in_result:
            self.fail(
                "%s - Missing manifest names: %s, Extra manifest names: %s" %
                (key, list(extra_in_correct), list(extra_in_result)))

    def assertCryptoCompressionValid(self):
        for result_img, correct_img in self.exr_result_images:
            result_compression = next(x.value
                                      for x in result_img.spec().extra_attribs
                                      if x.name == "compression")
            correct_compression = next(
                x.value for x in correct_img.spec().extra_attribs
                if x.name == "compression")
            self.assertEqual(
                result_compression, correct_compression,
                "Compression of result images does not match. (%s vs %s)" %
                (result_compression, correct_compression))
            self.assertIn(
                result_compression, {'none', 'zip', 'zips'},
                "Compression not of an allowed type: %s" % result_compression)

    def assertAllManifestsValidAndMatch(self):
        """
        Tests manifests match and are valid, and tests that all other cryptomatte
        metadata is equal.
        """
        for result_img, correct_img in self.exr_result_images:
            self.assertSameChannels(result_img, correct_img)
            result_md = self.crypto_metadata(result_img)
            correct_md = self.crypto_metadata(correct_img)

            for key in correct_md:
                self.assertIn(key, result_md,
                              "Result missing metadata key: %s" % key)
            for key in result_md:
                self.assertIn(key, correct_md,
                              "Result has extra metadata key: %s" % key)

            found_manifest = False
            for key in correct_md:
                if key.endswith("/manifest"):
                    self.assertManifestsAreValidAndMatch(
                        result_md, correct_md, key)
                    found_manifest = True
                else:
                    self.assertEqual(correct_md[key], result_md[key],
                                     "Metadata doesn't match: %s vs %s " %
                                     (result_md[key], correct_md[key]))
            self.assertTrue(found_manifest, "No manifest found")

    def assertCryptomattePixelsMatch(self,
                                     rms_tolerance=0.01,
                                     very_different_num_tolerance=4,
                                     print_result=False):
        """
        Tests pixels match in terms of coverage per ID. Normal image diff doesn't work here with any
        tolerance, because reshuffled IDs (for different sampling) cause giant errors. As a result,
        comparison is more costly, but better geared for Cryptomatte.
        """
        import math

        def get_id_coverage_dict(pixel_values, ch_pair_idxs):
            return {
                pixel_values[x]: pixel_values[y]
                for x, y, in ch_pair_idxs if (x != 0.0 or y != 0.0)
            }

        big_dif_tolerance = 0.3

        for result_img, correct_img in self.exr_result_images:
            result_nested_md = self.sorted_crypto_metadata(result_img)
            correct_nested_md = self.sorted_crypto_metadata(correct_img)

            total_count = 0
            very_different_count = 0
            squared_error = 0.0
            for row in range(0, 128):
                for column in range(0, 128):
                    result_pixel = result_img.getpixel(row, column)
                    correct_pixel = correct_img.getpixel(row, column)

                    for cryp_key in result_nested_md:
                        result_id_cov = get_id_coverage_dict(
                            result_pixel,
                            result_nested_md[cryp_key]["ch_pair_idxs"])
                        correct_id_cov = get_id_coverage_dict(
                            correct_pixel,
                            correct_nested_md[cryp_key]["ch_pair_idxs"])
                        for id_val, cov in correct_id_cov.iteritems():
                            total_count += 1
                            delta = abs(cov - (result_id_cov.get(id_val, 0.0)))
                            squared_error += delta * delta
                            if delta > big_dif_tolerance:
                                very_different_count += 1
                        for id_val, cov in result_id_cov.iteritems():
                            if id_val not in correct_id_cov:
                                total_count += 1
                                delta = cov
                                squared_error += delta * delta
                                if delta > big_dif_tolerance:
                                    very_different_count += 1

            self.assertTrue(total_count, "No values in %s" % result_img.name)

            rms = math.sqrt(squared_error / float(total_count))
            if print_result:
                print(self.id(), "Root mean square error: ", rms,
                      "Number of very different pixels: ",
                      very_different_count)

            self.assertTrue(
                very_different_count < very_different_num_tolerance,
                "%s matte pixels were very different (max tolerated: %s). " %
                (very_different_count, very_different_num_tolerance))
            self.assertTrue(
                rms < rms_tolerance,
                "Root mean square error was greater than %s. " % rms_tolerance)

    def assertNonCryptomattePixelsMatch(self, rms_tolerance=0.01):
        """
        Very simple tolerance test for non-cryptomatte pixels.
        """
        import math

        for result_img, correct_img in self.result_images:
            result_nested_md = self.sorted_crypto_metadata(result_img)
            correct_nested_md = self.sorted_crypto_metadata(correct_img)

            result_channels = []
            for cryp_key in result_nested_md:
                for x, y in result_nested_md[cryp_key]["ch_pair_idxs"]:
                    result_channels += [x, y]

            correct_channels = []
            for cryp_key in correct_nested_md:
                for x, y in correct_nested_md[cryp_key]["ch_pair_idxs"]:
                    correct_channels += [x, y]

            self.assertEqual(result_channels, correct_channels, "Channels don't match.")
            result_channels = set(result_channels)
            channels_to_check = [
                x for x in range(len(result_img.spec().channelnames))
                if x not in result_channels
            ]
            squared_errors = [
                0.0 for x in range(len(result_img.spec().channelnames))
            ]
            total_count = 0
            squared_error = 0.0
            for row in range(0, 128):
                for column in range(0, 128):
                    result_pixel = result_img.getpixel(row, column)
                    correct_pixel = correct_img.getpixel(row, column)

                    for i in channels_to_check:
                        delta = abs(result_pixel[i] - correct_pixel[i])
                        squared_errors[i] += delta * delta
                        total_count += 1

            for i in channels_to_check:
                squared_error = squared_errors[i]
                rms = math.sqrt(squared_error / float(total_count))
                self.assertTrue(
                    rms < rms_tolerance,
                    "Root mean square error was greater than %s. (Channel: %s)" %
                    (rms_tolerance, result_img.spec().channelnames[i]))

#############################################
# Cryptomatte test cases themselves
#############################################
"""
Testing to do list:
    mixed standard and custom cryptomattes
    Non-exrs specified
"""


class Cryptomatte000(CryptomatteTestBase):
    """
    A typical Mtoa configuration, (except with mayaShadingEngines removed)
    Some face assignments, some opacity, namespaces, some default namespaces, some
    overrides on namespaces.

    Has a non_AOV shader to test for regressions to an Arnold 5.1 crash.

    Settings:
        naming style: maya and c4d
        exr: single
        manifest: embedded
        strip namespaces: on
        preview_in_exr: off
        overrides:
            Some face assignments
            crypto_asset_override
            per-face crypto_object_override
            Matte objects
    """
    ass = "cryptomatte/000_mtoa_basic.ass"
    arnold_v = 6
    arnold_t = 0

    def test_compression_and_manifests(self):
        self.assertAllManifestsValidAndMatch()
        self.assertCryptoCompressionValid()

    def test_results_all_present(self):
        self.assertAllResultFilesPresent()

    def test_cryptomatte_pixels(self):
        self.assertCryptomattePixelsMatch()

    def test_unit_tests_ran(self):
        with open(self.result_log) as f:
            log_contents = f.read()
            self.assertIn("Cryptomatte unit tests: Running", log_contents,
                          "C++ unit test did not run. ")
            self.assertIn("Cryptomatte unit tests: Complete", log_contents,
                          "C++ unit test did not complete. ")

    @unittest.skip("Not necessary outside of distributing binaries")
    def test_build_compatibility(self):
        """ Tests that builds maximize compatibility with 
        later versions of Arnold. Currently this means building with
        6.0.0.0 for 6.0.* and
        6.2.0.0 for 6.2.*. 
        """
        legal_versions = ['6.0.0.0', '6.1.0.0', '6.2.0.0', '7.0.0.0']
        legal_phrases = ['cryptomatte uses Arnold %s' % x for x in legal_versions]
        with open(self.result_log) as f:
            log_contents = f.read()
            self.assertTrue(
                any(x in log_contents for x in legal_phrases),
                ("Cryptomatte not built against a "
                 "compatibility-maximizing version (%s). ") % legal_versions)

    def test_non_cryptomatte_pixels(self):
        self.assertNonCryptomattePixelsMatch()


class Cryptomatte001(CryptomatteTestBase):
    """
    Stripped down version of 000, with:
        64px
        manifest: sidecar
        Special characters cryptomatte:
            Custom Cryptomatte, where all names contain special characters.
            quotes, unicode, and slashes
    """
    ass = "cryptomatte/001_sidecars.ass"

    def test_compression_and_manifests(self):
        self.assertAllManifestsValidAndMatch()
        self.assertCryptoCompressionValid()

    def test_results_all_present(self):
        self.assertAllResultFilesPresent()

    def test_cryptomatte_pixels(self):
        self.assertCryptomattePixelsMatch()


class Cryptomatte002(CryptomatteTestBase):
    """
    Stripped down version of 000, with:
        64px
        preview_in_exr: off (with jpeg driver to simulate display driver)
        Multicamera renders with embedded manifests
    """
    ass = "cryptomatte/002_multicam.ass"
    arnold_t = 0

    def test_compression_and_manifests(self):
        self.assertAllManifestsValidAndMatch()
        self.assertCryptoCompressionValid()

    def test_results_all_present(self):
        self.assertAllResultFilesPresent()

    def test_cryptomatte_pixels(self):
        self.assertCryptomattePixelsMatch()

    def test_non_cryptomatte_pixels(self):
        self.assertNonCryptomattePixelsMatch()


class Cryptomatte003(CryptomatteTestBase):
    """
    Stripped down version of 000, with:
        64px
        Multicamera renders with sidecar manifests.
            One camera generates exr files per AOV, other one generates one EXR file.
    """
    ass = "cryptomatte/003_multicam_sidecars.ass"

    def test_compression_and_manifests(self):
        self.assertAllManifestsValidAndMatch()
        self.assertCryptoCompressionValid()

    def test_results_all_present(self):
        self.assertAllResultFilesPresent()

    def test_cryptomatte_pixels(self):
        self.assertCryptomattePixelsMatch()


class Cryptomatte010(CryptomatteTestBase):
    """
    Lots of instances, in a typical HtoA configuration.

    Adaptive sampling.

    Also tests non-Cryptomatte pixels (e.g. preview images)

    Settings:
        naming style: houdini
        exr: multi
        manifest: embedded
        strip namespaces: off
        overrides:
            crypto_asset on instances and instance masters
            crypto_object_offset on instance masters
            crypto_material_offset on instance masters
    """
    ass = "cryptomatte/010_htoa_instances.ass"

    def test_compression_and_manifests(self):
        self.assertAllManifestsValidAndMatch()
        self.assertCryptoCompressionValid()

    def test_results_all_present(self):
        self.assertAllResultFilesPresent()

    def test_cryptomatte_pixels(self):
        self.assertCryptomattePixelsMatch()


class Cryptomatte020(CryptomatteTestBase):
    """
    Has some custom cryptomattes. Some objects have values set, others do not.
    Some per-face user data as well.

    Settings:
        naming style: maya
        exr: single
        manifest: embedded
        strip namespaces: N/A

    Something has strings per polygon.
    """
    ass = "cryptomatte/020_custom_cryptomattes.ass"

    def test_compression_and_manifests(self):
        self.assertAllManifestsValidAndMatch()
        self.assertCryptoCompressionValid()

    def test_results_all_present(self):
        self.assertAllResultFilesPresent()

    def test_cryptomatte_pixels(self):
        self.assertCryptomattePixelsMatch()


class Cryptomatte030(CryptomatteTestBase):
    """
    Writes to a jpeg, which should have preview images. 
    """
    ass = "cryptomatte/030_jpeg_driver.ass"

    def test_results_all_present(self):
        self.assertAllResultFilesPresent()

    def test_result_images_equal(self):
        self.assertAllResultImagesEqual(0.1)

    def test_non_cryptomatte_pixels(self):
        self.assertNonCryptomattePixelsMatch()


class CryptomatteSetup(unittest.TestCase):

    def setUp(self):
        self.output_file_name = os.path.join(tempfile.gettempdir(), "result.exr")

        ai.AiBegin()
        ai.AiMsgSetConsoleFlags(ai.AI_LOG_NONE)
        ai.AiMsgSetConsoleFlags(ai.AI_LOG_WARNINGS | ai.AI_LOG_ERRORS)

        options = ai.AiUniverseGetOptions()
        ai.AiNodeSetBool(options, "skip_license_check", True)
        ai.AiNodeSetInt(options, "xres", 16);
        ai.AiNodeSetInt(options, "yres", 16);

        self.my_camera = ai.AiNode("persp_camera", "my_camera", None)
        self.my_filter = ai.AiNode("gaussian_filter", "my_filter", None)
        self.my_driver = ai.AiNode("driver_exr", "my_driver", None)
        self.my_cryptomatte = ai.AiNode("cryptomatte", "my_cryptomatte", None)

        ai.AiNodeSetStr(self.my_driver, "filename", self.output_file_name)
        ai.AiNodeSetPtr(options, "aov_shaders", self.my_cryptomatte)

        self.assertTrue(
            self.my_cryptomatte, 
            ("Cryptomatte node could not be created, plugin may not be "
             "loaded in Python. (There may be binary compatibily issues "
             "with Python). "))

    def tearDown(self):
        if os.path.exists(self.output_file_name):
            os.remove(self.output_file_name)
        ai.AiEnd()
        
    def list_to_array(self, python_list):
        arnold_array = ai.AiArrayAllocate(len(python_list), 1, ai.AI_TYPE_STRING)
        for i, element in enumerate(python_list):
            ai.AiArraySetStr(arnold_array, i, element)
        return arnold_array

    def array_to_list(self, arnold_array):
        py_list = [] 
        for i in xrange(ai.AiArrayGetNumElements(arnold_array)):
            py_list.append(ai.AiArrayGetStr(arnold_array, i))
        return py_list

    def test_half_driver(self):
        """ Tests setup of outputs occurs correctly with a half precision driver 
        All non-cryptomatte aovs should be set to half, after driver is set to full.
        """
        ai.AiNodeSetBool(self.my_driver, "half_precision", True)

        outputs_init = [
            "RGBA RGBA my_filter my_driver",
            "test_aov1 RGB my_filter my_driver HALF",
            "crypto_asset RGBA my_filter my_driver",
        ]
        correct_outputs = [
            "RGBA RGBA my_filter my_driver HALF",
            "test_aov1 RGB my_filter my_driver HALF",
            "crypto_asset RGBA cryptomatte_noop_filter my_driver HALF",
            "crypto_asset00 FLOAT crypto_asset_filter00 my_driver",
            "crypto_asset01 FLOAT crypto_asset_filter01 my_driver",
            "crypto_asset02 FLOAT crypto_asset_filter02 my_driver",
        ]
        self._test_setup(outputs_init, correct_outputs)

    def test_full_driver(self):
        """ Tests setup of outputs occurs correctly with a full precision driver 
        HALF aovs should be preserved, but no new AOVs should be set to HALF.
        """
        ai.AiNodeSetBool(self.my_driver, "half_precision", False)
        
        outputs_init = [
            "RGBA RGBA my_filter my_driver",
            "test_aov1 RGB my_filter my_driver HALF",
            "crypto_asset RGBA my_filter my_driver",
        ]
        correct_outputs = [
            "RGBA RGBA my_filter my_driver",
            "test_aov1 RGB my_filter my_driver HALF",
            "crypto_asset RGBA cryptomatte_noop_filter my_driver",
            "crypto_asset00 FLOAT crypto_asset_filter00 my_driver",
            "crypto_asset01 FLOAT crypto_asset_filter01 my_driver",
            "crypto_asset02 FLOAT crypto_asset_filter02 my_driver",
        ]
        self._test_setup(outputs_init, correct_outputs)

    def test_driver_preview(self):
        """ Tests setup of outputs occurs correctly with a full precision driver 
        HALF aovs should be preserved, but no new AOVs should be set to HALF.
        """
        ai.AiNodeSetBool(self.my_driver, "half_precision", False)
        ai.AiNodeSetBool(self.my_cryptomatte, "preview_in_exr", True)

        outputs_init = [
            "RGBA RGBA my_filter my_driver",
            "crypto_asset RGBA my_filter my_driver",
        ]
        correct_outputs = [
            "RGBA RGBA my_filter my_driver",
            "crypto_asset RGBA my_filter my_driver",
            "crypto_asset00 FLOAT crypto_asset_filter00 my_driver",
            "crypto_asset01 FLOAT crypto_asset_filter01 my_driver",
            "crypto_asset02 FLOAT crypto_asset_filter02 my_driver",
        ]
        self._test_setup(outputs_init, correct_outputs)

    def _test_setup(self, outputs_init, correct_outputs):
        """ Tests setup of outputs occurs correctly with a full precision driver 
        HALF aovs should be preserved, but no new AOVs should be set to HALF.
        """
        options = ai.AiUniverseGetOptions()
        orig_num = len(outputs_init)

        ai.AiNodeSetArray(options, "outputs", self.list_to_array(outputs_init));

        ai.AiRender()

        found_outputs = self.array_to_list(ai.AiNodeGetArray(options, "outputs"))

        # check original aovs
        self.assertEqual(correct_outputs[:orig_num], found_outputs[:orig_num])
        # check addutional aovs
        self.assertEqual(correct_outputs[orig_num:], found_outputs[orig_num:])
