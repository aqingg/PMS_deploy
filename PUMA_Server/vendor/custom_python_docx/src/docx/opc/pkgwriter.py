"""Provides low-level, write-only API to serialized (OPC) package.

OPC stands for Open Packaging Convention. This is e, essentially an implementation of
OpcPackage.save().
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.oxml import CT_Types, serialize_part_xml
from docx.opc.packuri import CONTENT_TYPES_URI, PACKAGE_URI
from docx.opc.phys_pkg import PhysPkgWriter
from docx.opc.shared import CaseInsensitiveDict
from docx.opc.spec import default_content_types

if TYPE_CHECKING:
    from docx.opc.part import Part


class PackageWriter:
    """Writes a zip-format OPC package to `pkg_file`, where `pkg_file` can be either a
    path to a zip file (a string) or a file-like object.

    Its single API method, :meth:`write`, is static, so this class is not intended to be
    instantiated.
    """

    @staticmethod
    def write(pkg_file, pkg_rels, parts, vba_project_blob=None):
        """Write a physical package (.pptx file) to `pkg_file`..."""
        phys_writer = PhysPkgWriter(pkg_file)
        # 把 vba_project_blob 传给 _write_content_types_stream
        PackageWriter._write_content_types_stream(phys_writer, parts, vba_project_blob)
        PackageWriter._write_pkg_rels(phys_writer, pkg_rels)
        PackageWriter._write_parts(phys_writer, parts)

        if vba_project_blob:
            # 使用 PackURI 来确保路径格式正确
            from docx.opc.packuri import PackURI
            vba_partname = PackURI('/word/vbaProject.bin')
            phys_writer.write(vba_partname, vba_project_blob)

        phys_writer.close()

    @staticmethod
    def _write_content_types_stream(phys_writer, parts, vba_project_blob=None):
        """Write ``[Content_Types].xml`` part..."""
        # 把 vba_project_blob 传给 _ContentTypesItem
        cti = _ContentTypesItem.from_parts(parts, vba_project_blob)
        phys_writer.write(CONTENT_TYPES_URI, cti.blob)

    @staticmethod
    def _write_parts(phys_writer: PhysPkgWriter, parts: Iterable[Part]):
        """Write the blob of each part in `parts` to the package, along with a rels item
        for its relationships if and only if it has any."""
        for part in parts:
            phys_writer.write(part.partname, part.blob)
            if len(part.rels):
                phys_writer.write(part.partname.rels_uri, part.rels.xml)

    @staticmethod
    def _write_pkg_rels(phys_writer, pkg_rels):
        """Write the XML rels item for `pkg_rels` ('/_rels/.rels') to the package."""
        phys_writer.write(PACKAGE_URI.rels_uri, pkg_rels.xml)


class _ContentTypesItem:
    """Service class that composes a content types item ([Content_Types].xml) based on a
    list of parts.

    Not meant to be instantiated directly, its single interface method is xml_for(),
    e.g. ``_ContentTypesItem.xml_for(parts)``.
    """

    def __init__(self):
        self._defaults = CaseInsensitiveDict()
        self._overrides = {}

    @property
    def blob(self):
        """Return XML form of this content types item, suitable for storage as
        ``[Content_Types].xml`` in an OPC package."""
        return serialize_part_xml(self._element)

    @classmethod
    def from_parts(cls, parts, vba_project_blob=None):
        """Return content types XML mapping each part in `parts`..."""
        cti = cls()
        cti._defaults["rels"] = CT.OPC_RELATIONSHIPS
        cti._defaults["xml"] = CT.XML
        for part in parts:
            cti._add_content_type(part.partname, part.content_type)
        
        # 为宏添加 Override
        if vba_project_blob:
            from docx.opc.packuri import PackURI
            vba_partname = PackURI('/word/vbaProject.bin')
            vba_content_type = 'application/vnd.ms-office.vbaProject'
            # 直接添加到 overrides 字典
            cti._overrides[vba_partname] = vba_content_type
        
        return cti

    def _add_content_type(self, partname, content_type):
        """Add a content type for the part with `partname` and `content_type`, using a
        default or override as appropriate."""
        ext = partname.ext
        if (ext.lower(), content_type) in default_content_types:
            self._defaults[ext] = content_type
        else:
            self._overrides[partname] = content_type

    @property
    def _element(self):
        """Return XML form of this content types item, suitable for storage as
        ``[Content_Types].xml`` in an OPC package.

        Although the sequence of elements is not strictly significant, as an aid to
        testing and readability Default elements are sorted by extension and Override
        elements are sorted by partname.
        """
        _types_elm = CT_Types.new()
        for ext in sorted(self._defaults.keys()):
            _types_elm.add_default(ext, self._defaults[ext])
        for partname in sorted(self._overrides.keys()):
            _types_elm.add_override(partname, self._overrides[partname])
        return _types_elm
