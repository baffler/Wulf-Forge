// Git-friendly Ghidra program export for Wulf-Forge reverse engineering.
// @category WulfForge.Export

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Iterator;

import ghidra.app.script.GhidraScript;
import ghidra.framework.model.DomainFile;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.address.AddressRange;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.listing.Bookmark;
import ghidra.program.model.listing.BookmarkManager;
import ghidra.program.model.listing.CodeUnitComments;
import ghidra.program.model.listing.CommentType;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.ExternalLocation;
import ghidra.program.model.symbol.ExternalLocationIterator;
import ghidra.program.model.symbol.ExternalManager;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolTable;

public class ExportProgramText extends GhidraScript {
	private static final CommentType[] COMMENT_TYPES = {
		CommentType.PLATE,
		CommentType.PRE,
		CommentType.EOL,
		CommentType.REPEATABLE,
		CommentType.POST
	};

	private Counts counts = new Counts();

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length != 1) {
			throw new IllegalArgumentException(
				"Usage: ExportProgramText.java <repo-root-or-reverseengineering-dir>");
		}
		if (currentProgram == null) {
			throw new IllegalStateException("No current program is loaded.");
		}

		File root = new File(args[0]);
		if (!"reverseengineering".equals(root.getName())) {
			root = new File(root, "reverseengineering");
		}
		File programDir = new File(new File(root, "programs"), slugFor(domainPath()));
		if (!programDir.exists() && !programDir.mkdirs()) {
			throw new IOException("Unable to create " + programDir.getAbsolutePath());
		}

		exportMemoryMap(programDir);
		exportFunctions(programDir);
		exportSymbols(programDir);
		exportComments(programDir);
		exportBookmarks(programDir);
		exportStrings(programDir);
		exportExternalLibraries(programDir);
		exportExternalLocations(programDir);
		exportExternalEntryPoints(programDir);
		exportMetadata(programDir);

		println("Exported " + domainPath() + " to " + programDir.getAbsolutePath());
	}

	private void exportMetadata(File dir) throws IOException {
		DomainFile file = currentProgram.getDomainFile();
		try (PrintWriter out = writer(dir, "metadata.json")) {
			out.println("{");
			json(out, "project_file", safe(file == null ? null : file.getPathname()), true);
			json(out, "program_name", currentProgram.getName(), true);
			json(out, "executable_path", currentProgram.getExecutablePath(), true);
			json(out, "executable_format", currentProgram.getExecutableFormat(), true);
			json(out, "executable_md5", currentProgram.getExecutableMD5(), true);
			json(out, "executable_sha256", currentProgram.getExecutableSHA256(), true);
			json(out, "language_id", String.valueOf(currentProgram.getLanguageID()), true);
			json(out, "compiler", currentProgram.getCompiler(), true);
			json(out, "compiler_spec", String.valueOf(currentProgram.getCompilerSpec().getCompilerSpecID()), true);
			json(out, "image_base", addr(currentProgram.getImageBase()), true);
			json(out, "min_address", addr(currentProgram.getMinAddress()), true);
			json(out, "max_address", addr(currentProgram.getMaxAddress()), true);
			json(out, "default_pointer_size", String.valueOf(currentProgram.getDefaultPointerSize()), true);
			out.println("  \"counts\": {");
			json(out, "memory_blocks", counts.memoryBlocks, true, 4);
			json(out, "functions", counts.functions, true, 4);
			json(out, "defined_symbols", counts.definedSymbols, true, 4);
			json(out, "comments", counts.comments, true, 4);
			json(out, "bookmarks", counts.bookmarks, true, 4);
			json(out, "strings", counts.strings, true, 4);
			json(out, "external_libraries", counts.externalLibraries, true, 4);
			json(out, "external_locations", counts.externalLocations, true, 4);
			json(out, "external_entry_points", counts.externalEntryPoints, false, 4);
			out.println("  }");
			out.println("}");
		}
	}

	private void exportMemoryMap(File dir) throws IOException {
		try (PrintWriter out = writer(dir, "memory_map.tsv")) {
			out.println("name\tstart\tend\tsize\tread\twrite\texecute\tinitialized\tloaded\toverlay\ttype\tsource\tcomment");
			for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
				counts.memoryBlocks++;
				out.println(row(
					block.getName(),
					addr(block.getStart()),
					addr(block.getEnd()),
					String.valueOf(block.getSize()),
					String.valueOf(block.isRead()),
					String.valueOf(block.isWrite()),
					String.valueOf(block.isExecute()),
					String.valueOf(block.isInitialized()),
					String.valueOf(block.isLoaded()),
					String.valueOf(block.isOverlay()),
					String.valueOf(block.getType()),
					block.getSourceName(),
					block.getComment()));
			}
		}
	}

	private void exportFunctions(File dir) throws IOException {
		Listing listing = currentProgram.getListing();
		try (PrintWriter out = writer(dir, "functions.tsv")) {
			out.println("entry\tname\tfull_name\tnamespace\tname_source\tsignature_source\tcalling_convention\treturn_type\tparameter_count\tis_thunk\tthunk_target\tis_external\tbody_ranges\tcomment\trepeatable_comment\tprototype");
			FunctionIterator functions = listing.getFunctions(true);
			while (functions.hasNext()) {
				Function function = functions.next();
				counts.functions++;
				Symbol symbol = function.getSymbol();
				Function thunkTarget = function.isThunk() ? function.getThunkedFunction(true) : null;
				out.println(row(
					addr(function.getEntryPoint()),
					function.getName(),
					function.getName(true),
					namespaceName(function.getParentNamespace()),
					symbol == null ? "" : String.valueOf(symbol.getSource()),
					String.valueOf(function.getSignatureSource()),
					function.getCallingConventionName(),
					String.valueOf(function.getReturnType()),
					String.valueOf(function.getParameterCount()),
					String.valueOf(function.isThunk()),
					thunkTarget == null ? "" : thunkTarget.getName(true),
					String.valueOf(function.isExternal()),
					ranges(function.getBody()),
					function.getComment(),
					function.getRepeatableComment(),
					function.getPrototypeString(true, true)));
			}
		}
	}

	private void exportSymbols(File dir) throws IOException {
		SymbolTable symbols = currentProgram.getSymbolTable();
		try (PrintWriter out = writer(dir, "defined_symbols.tsv")) {
			out.println("address\ttype\tname\tfull_name\tnamespace\tsource\tprimary\texternal\texternal_entry");
			SymbolIterator iterator = symbols.getSymbolIterator(true);
			while (iterator.hasNext()) {
				Symbol symbol = iterator.next();
				if (symbol.isDynamic()) {
					continue;
				}
				counts.definedSymbols++;
				out.println(row(
					addr(symbol.getAddress()),
					String.valueOf(symbol.getSymbolType()),
					symbol.getName(),
					symbol.getName(true),
					namespaceName(symbol.getParentNamespace()),
					String.valueOf(symbol.getSource()),
					String.valueOf(symbol.isPrimary()),
					String.valueOf(symbol.isExternal()),
					String.valueOf(symbol.isExternalEntryPoint())));
			}
		}
	}

	private void exportComments(File dir) throws IOException {
		Listing listing = currentProgram.getListing();
		try (PrintWriter out = writer(dir, "comments.tsv")) {
			out.println("address\ttype\tcomment");
			AddressIterator addresses = listing.getCommentAddressIterator(currentProgram.getMemory(), true);
			while (addresses.hasNext()) {
				Address address = addresses.next();
				CodeUnitComments comments = listing.getAllComments(address);
				for (CommentType type : COMMENT_TYPES) {
					String comment = comments.getComment(type);
					if (comment != null && !comment.isEmpty()) {
						counts.comments++;
						out.println(row(addr(address), type.name(), comment));
					}
				}
			}
		}
	}

	private void exportBookmarks(File dir) throws IOException {
		BookmarkManager manager = currentProgram.getBookmarkManager();
		try (PrintWriter out = writer(dir, "bookmarks.tsv")) {
			out.println("address\ttype\tcategory\tcomment");
			Iterator<Bookmark> bookmarks = manager.getBookmarksIterator();
			while (bookmarks.hasNext()) {
				Bookmark bookmark = bookmarks.next();
				counts.bookmarks++;
				out.println(row(
					addr(bookmark.getAddress()),
					bookmark.getTypeString(),
					bookmark.getCategory(),
					bookmark.getComment()));
			}
		}
	}

	private void exportStrings(File dir) throws IOException {
		Listing listing = currentProgram.getListing();
		try (PrintWriter out = writer(dir, "strings.tsv")) {
			out.println("address\tlength\tdata_type\tvalue");
			DataIterator dataIterator = listing.getDefinedData(true);
			while (dataIterator.hasNext()) {
				Data data = dataIterator.next();
				if (!data.hasStringValue()) {
					continue;
				}
				counts.strings++;
				Object value = data.getValue();
				out.println(row(
					addr(data.getAddress()),
					String.valueOf(data.getLength()),
					String.valueOf(data.getDataType()),
					value == null ? data.getDefaultValueRepresentation() : String.valueOf(value)));
			}
		}
	}

	private void exportExternalLibraries(File dir) throws IOException {
		ExternalManager manager = currentProgram.getExternalManager();
		String[] libraries = manager.getExternalLibraryNames();
		Arrays.sort(libraries, String.CASE_INSENSITIVE_ORDER);
		try (PrintWriter out = writer(dir, "external_libraries.tsv")) {
			out.println("library\tpath");
			for (String library : libraries) {
				counts.externalLibraries++;
				out.println(row(library, manager.getExternalLibraryPath(library)));
			}
		}
	}

	private void exportExternalLocations(File dir) throws IOException {
		ExternalManager manager = currentProgram.getExternalManager();
		String[] libraries = manager.getExternalLibraryNames();
		Arrays.sort(libraries, String.CASE_INSENSITIVE_ORDER);
		try (PrintWriter out = writer(dir, "external_locations.tsv")) {
			out.println("library\tlabel\toriginal_imported_name\tparent\taddress\texternal_space_address\tis_function\tsource\tdata_type");
			for (String library : libraries) {
				ExternalLocationIterator locations = manager.getExternalLocations(library);
				while (locations.hasNext()) {
					ExternalLocation location = locations.next();
					counts.externalLocations++;
					out.println(row(
						location.getLibraryName(),
						location.getLabel(),
						location.getOriginalImportedName(),
						location.getParentName(),
						addr(location.getAddress()),
						addr(location.getExternalSpaceAddress()),
						String.valueOf(location.isFunction()),
						String.valueOf(location.getSource()),
						String.valueOf(location.getDataType())));
				}
			}
		}
	}

	private void exportExternalEntryPoints(File dir) throws IOException {
		SymbolTable symbols = currentProgram.getSymbolTable();
		try (PrintWriter out = writer(dir, "external_entry_points.tsv")) {
			out.println("address\tprimary_symbol");
			AddressIterator addresses = symbols.getExternalEntryPointIterator();
			while (addresses.hasNext()) {
				Address address = addresses.next();
				counts.externalEntryPoints++;
				Symbol primary = symbols.getPrimarySymbol(address);
				out.println(row(addr(address), primary == null ? "" : primary.getName(true)));
			}
		}
	}

	private String domainPath() {
		DomainFile file = currentProgram.getDomainFile();
		if (file == null) {
			return "/" + currentProgram.getName();
		}
		return file.getPathname();
	}

	private PrintWriter writer(File dir, String name) throws IOException {
		return new PrintWriter(new OutputStreamWriter(
			new FileOutputStream(new File(dir, name)), StandardCharsets.UTF_8));
	}

	private String namespaceName(ghidra.program.model.symbol.Namespace namespace) {
		return namespace == null ? "" : namespace.getName(true);
	}

	private String addr(Address address) {
		return address == null ? "" : address.toString();
	}

	private String ranges(AddressSetView set) {
		if (set == null || set.isEmpty()) {
			return "";
		}
		StringBuilder builder = new StringBuilder();
		for (AddressRange range : set) {
			if (builder.length() > 0) {
				builder.append(';');
			}
			builder.append(range.getMinAddress()).append('-').append(range.getMaxAddress());
		}
		return builder.toString();
	}

	private String slugFor(String value) {
		String slug = safe(value).replace('\\', '/');
		if (slug.startsWith("/")) {
			slug = slug.substring(1);
		}
		slug = slug.replaceAll("[^A-Za-z0-9._-]+", "__");
		slug = slug.replaceAll("__+", "__");
		if (slug.isEmpty()) {
			return "program";
		}
		return slug;
	}

	private String row(String... values) {
		StringBuilder builder = new StringBuilder();
		for (int i = 0; i < values.length; i++) {
			if (i > 0) {
				builder.append('\t');
			}
			builder.append(tsv(values[i]));
		}
		return builder.toString();
	}

	private String tsv(String value) {
		String encoded = safe(value)
			.replace("\\", "\\\\")
			.replace("\t", "\\t")
			.replace("\r", "\\r")
			.replace("\n", "\\n");
		if (encoded.isEmpty()) {
			return "\\N";
		}
		while (encoded.startsWith(" ")) {
			encoded = "\\s" + encoded.substring(1);
		}
		while (encoded.endsWith(" ")) {
			encoded = encoded.substring(0, encoded.length() - 1) + "\\s";
		}
		return encoded;
	}

	private String safe(String value) {
		return value == null ? "" : value;
	}

	private void json(PrintWriter out, String key, Object value, boolean comma) {
		json(out, key, value, comma, 2);
	}

	private void json(PrintWriter out, String key, Object value, boolean comma, int spaces) {
		String indent = " ".repeat(spaces);
		String encoded;
		if (value instanceof Number) {
			encoded = String.valueOf(value);
		}
		else {
			encoded = "\"" + jsonEscape(String.valueOf(value)) + "\"";
		}
		out.println(indent + "\"" + jsonEscape(key) + "\": " + encoded + (comma ? "," : ""));
	}

	private String jsonEscape(String value) {
		StringBuilder builder = new StringBuilder();
		for (int i = 0; i < value.length(); i++) {
			char ch = value.charAt(i);
			switch (ch) {
				case '\\':
					builder.append("\\\\");
					break;
				case '"':
					builder.append("\\\"");
					break;
				case '\b':
					builder.append("\\b");
					break;
				case '\f':
					builder.append("\\f");
					break;
				case '\n':
					builder.append("\\n");
					break;
				case '\r':
					builder.append("\\r");
					break;
				case '\t':
					builder.append("\\t");
					break;
				default:
					if (ch < 0x20) {
						builder.append(String.format("\\u%04x", (int) ch));
					}
					else {
						builder.append(ch);
					}
			}
		}
		return builder.toString();
	}

	private static class Counts {
		long memoryBlocks;
		long functions;
		long definedSymbols;
		long comments;
		long bookmarks;
		long strings;
		long externalLibraries;
		long externalLocations;
		long externalEntryPoints;
	}
}
